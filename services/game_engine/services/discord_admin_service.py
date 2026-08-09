import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from anyio import to_thread
from api.discord_dependencies import DiscordServiceContext
from core.api_errors import ApiProblem
from core.config import settings
from core.messages import message_placeholder_catalog, validate_custom_message_template
from core.permissions import ROLE_PERMISSIONS, ChannelPermission
from domain.config_schema import GameConfig, RewardDefinition
from domain.item_schema import ModifierScope
from domain.logic.formulas import geometric_first_success_stats
from domain.schemas.admin import ChannelCreateDTO
from domain.schemas.discord_admin import (
    ConfigPatchRequest,
    ConfigResetRequest,
    DiscordEventCreateRequest,
    DiscordEventPatchRequest,
    DiscordEventStartRequest,
    DiscordItemUpsertRequest,
    GuildBindRequest,
    ItemDropUpsertRequest,
    LegacyRewardImportRequest,
    LocationCreateRequest,
    LocationPatchRequest,
    MessageTemplatePatchRequest,
    PlayerItemGrantRequest,
    PlayerItemRevokeRequest,
    PlayerModifierSetRequest,
    RewardCreateRequest,
    RewardPatchRequest,
    VersionedStateRequest,
)
from infrastructure.models import (
    AdminAuditLog,
    LootTable,
    LootTableEntry,
    LootTableEntryStock,
    Channel,
    DiscordAccountLink,
    DiscordGuildBinding,
    FishingEvent,
    InventoryItem,
    ItemDefinition,
    PlayerModifier,
    RewardPool,
    UserProgress,
)
from infrastructure.redis_client import RedisClient
from infrastructure.repositories.channel_repo import ChannelRepository
from infrastructure.repositories.fishing_cast_query_repo import FishingCastQueryRepository
from infrastructure.repositories.inventory_repo import InventoryRepository
from infrastructure.repositories.user_repo import UserRepository
from pydantic import TypeAdapter, ValidationError
from services.auth_service import AuthService
from services.eventing.event_lifecycle_service import FishingEventLifecycleService
from services.idempotency_service import IdempotencyService
from services.inventory_service import InventoryService
from services.legacy_rewards import convert_legacy_rewards
from services.player_modifier_service import PlayerModifierService
from sqlalchemy.orm.attributes import flag_modified

REWARD_ADAPTER = TypeAdapter(RewardDefinition)
CONFIG_SECTIONS = {
    "xp": {"xp_base", "xp_exponent"},
    "economy": {"sell_max_bonus", "sell_mid_level", "sell_rate", "buy_rate"},
    "robbery": {
        "rob_min_chance",
        "rob_max_chance",
        "rob_resist_divisor",
        "rob_loss_divisor",
        "rob_base_chance",
    },
    "cooldown": {"fishing_cooldown", "subs_fishing_cooldown"},
}

# Cooldowns used for the item-drop "expected active time" preview (audit §10).
DROP_PREVIEW_COOLDOWNS = (Decimal("5"), Decimal("7.5"), Decimal("10"))


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _dec(value) -> str | None:
    if value is None:
        return None
    return str(Decimal(value))


def _format_delta(value) -> str | None:
    if value is None:
        return None
    return _dec(value)


def _parse_datetime(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class DiscordAdminService:
    def __init__(self, db):
        self.db = db
        self.channel_repo = ChannelRepository(db)
        self.auth_service = AuthService(self.channel_repo)
        self.redis = RedisClient.get_client()
        self.idempotency = IdempotencyService(db)
        self.event_lifecycle = FishingEventLifecycleService(self.channel_repo)

    def start_link(self, context: DiscordServiceContext) -> dict[str, Any]:
        limit_key = f"fish:discord:link-rate:{context.discord_user_id}"
        attempts = int(self.redis.incr(limit_key))
        if attempts == 1:
            self.redis.expire(limit_key, 600)
        if attempts > 3:
            ttl = max(int(self.redis.ttl(limit_key)), 1)
            raise ApiProblem(
                429,
                "PERMISSION_DENIED",
                f"Link rate limit exceeded. Retry in {ttl}s",
                request_id=context.request_id,
            )

        state = secrets.token_urlsafe(32)
        payload = {
            "discord_user_id": context.discord_user_id,
            "discord_guild_id": context.discord_guild_id,
            "request_id": context.request_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.redis.setex(f"fish:discord:oauth:{state}", 600, json.dumps(payload))
        query = urlencode(
            {
                "client_id": settings.TWITCH_CLIENT_ID,
                "redirect_uri": settings.TWITCH_DISCORD_REDIRECT_URI,
                "response_type": "code",
                "scope": "user:read:email",
                "state": state,
            }
        )
        return {
            "authorization_url": f"https://id.twitch.tv/oauth2/authorize?{query}",
            "expires_in": 600,
        }

    async def complete_link(self, state: str, code: str) -> dict[str, Any]:
        raw_payload = await to_thread.run_sync(
            self.redis.getdel,
            f"fish:discord:oauth:{state}",
        )
        if not raw_payload:
            raise ApiProblem(400, "VALIDATION_ERROR", "OAuth state is invalid or expired")
        payload = json.loads(raw_payload)
        user_data = await self.auth_service.authenticate_twitch_user(
            code,
            settings.TWITCH_DISCORD_REDIRECT_URI,
        )
        return await to_thread.run_sync(self._persist_link, payload, user_data)

    def _persist_link(
        self,
        payload: dict[str, Any],
        user_data: dict[str, Any],
    ) -> dict[str, Any]:
        discord_user_id = str(payload["discord_user_id"])
        twitch_user_id = str(user_data["twitch_id"])

        conflicting_link = (
            self.db.query(DiscordAccountLink)
            .filter(
                DiscordAccountLink.twitch_user_id == twitch_user_id,
                DiscordAccountLink.discord_user_id != discord_user_id,
                DiscordAccountLink.revoked_at.is_(None),
            )
            .first()
        )
        if conflicting_link:
            raise ApiProblem(409, "PERMISSION_DENIED", "Twitch account is already linked")
        link = (
            self.db.query(DiscordAccountLink)
            .filter(DiscordAccountLink.discord_user_id == discord_user_id)
            .first()
        )
        now = datetime.now(timezone.utc)
        if link and link.twitch_user_id != twitch_user_id and link.revoked_at is None:
            raise ApiProblem(409, "PERMISSION_DENIED", "Unlink the current Twitch account first")
        if not link:
            link = DiscordAccountLink(
                discord_user_id=discord_user_id,
                twitch_user_id=twitch_user_id,
                twitch_login=str(user_data["username"]),
                verified_at=now,
                last_verified_at=now,
            )
            self.db.add(link)
        else:
            link.twitch_user_id = twitch_user_id
            link.twitch_login = str(user_data["username"])
            link.verified_at = now
            link.last_verified_at = now
            link.revoked_at = None
        self.db.flush()
        return {
            "status": "linked",
            "twitch_login": link.twitch_login,
            "twitch_user_id": twitch_user_id,
        }

    def status(self, context: DiscordServiceContext) -> dict[str, Any]:
        link = self._get_link(context, required=False)
        binding = None
        if context.discord_guild_id:
            binding = (
                self.db.query(DiscordGuildBinding)
                .filter(DiscordGuildBinding.discord_guild_id == context.discord_guild_id)
                .first()
            )
        return {
            "linked": bool(link),
            "twitch": ({"id": link.twitch_user_id, "login": link.twitch_login} if link else None),
            "binding": self._serialize_binding(binding) if binding else None,
        }

    def unlink(self, context: DiscordServiceContext) -> dict[str, Any]:
        def mutation() -> dict[str, Any]:
            link = self._get_link(context)
            before = {"twitch_user_id": link.twitch_user_id, "twitch_login": link.twitch_login}
            self._audit(
                context,
                link.twitch_user_id,
                "discord.link.unlink",
                "discord_link",
                link.id,
                before,
                {},
            )
            self.db.delete(link)
            self.db.flush()
            return {"status": "unlinked"}

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "discord.link.unlink",
            {},
            context.request_id,
            mutation,
        )

    def bind_guild(self, context: DiscordServiceContext, data: GuildBindRequest) -> dict[str, Any]:
        if not context.discord_guild_id or not context.can_manage_guild:
            raise ApiProblem(
                403,
                "PERMISSION_DENIED",
                "Manage Guild permission is required",
                request_id=context.request_id,
            )

        def mutation() -> dict[str, Any]:
            link = self._get_link(context)
            channel = self.channel_repo.get_by_twitch_id(link.twitch_user_id)
            if not channel:
                channel = self.channel_repo.create(
                    ChannelCreateDTO(twitch_id=link.twitch_user_id, name=link.twitch_login)
                )
            if not self._find_pool(channel.id, "default"):
                self.db.add(
                    RewardPool(
                        channel_id=channel.id,
                        location_id="default",
                        location_name="Default",
                        rewards_data=[],
                        requirements={},
                    )
                )
                self.db.flush()
            existing = (
                self.db.query(DiscordGuildBinding)
                .filter(DiscordGuildBinding.discord_guild_id == context.discord_guild_id)
                .first()
            )
            channel_binding = (
                self.db.query(DiscordGuildBinding)
                .filter(
                    DiscordGuildBinding.channel_id == channel.id,
                    DiscordGuildBinding.discord_guild_id != context.discord_guild_id,
                )
                .first()
            )
            if channel_binding:
                raise ApiProblem(
                    409, "PERMISSION_DENIED", "Twitch channel is bound to another guild"
                )
            if existing and existing.channel_id != channel.id and not data.replace:
                raise ApiProblem(
                    409, "PERMISSION_DENIED", "Guild is already bound; confirmation required"
                )
            before = self._serialize_binding(existing) if existing else {}
            if not existing:
                existing = DiscordGuildBinding(
                    discord_guild_id=context.discord_guild_id,
                    channel_id=channel.id,
                    configured_by_discord_id=context.discord_user_id,
                )
                self.db.add(existing)
            else:
                existing.channel_id = channel.id
                existing.configured_by_discord_id = context.discord_user_id
            existing.management_channel_id = context.management_channel_id
            self.db.flush()
            after = self._serialize_binding(existing)
            self._audit(
                context,
                link.twitch_user_id,
                "discord.guild.bind",
                "guild_binding",
                existing.id,
                before,
                after,
            )
            return after

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "discord.guild.bind",
            data.model_dump(mode="json"),
            context.request_id,
            mutation,
        )

    def remove_guild_binding(self, context: DiscordServiceContext) -> dict[str, Any]:
        if not context.discord_guild_id or not context.can_manage_guild:
            raise ApiProblem(403, "PERMISSION_DENIED", "Manage Guild permission is required")

        def mutation() -> dict[str, Any]:
            channel, link = self._authorize(context, ChannelPermission.INTEGRATIONS_WRITE)
            binding = self._get_binding(context)
            before = self._serialize_binding(binding)
            self.db.delete(binding)
            self.db.flush()
            self._audit(
                context,
                link.twitch_user_id,
                "discord.guild.unbind",
                "guild_binding",
                binding.id,
                before,
                {},
            )
            return {"status": "unbound", "channel_twitch_id": channel.twitch_id}

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "discord.guild.unbind",
            {},
            context.request_id,
            mutation,
        )

    def list_player_modifiers(
        self, context, channel_twitch_id: str, viewer: str
    ) -> dict[str, Any]:
        channel, _ = self._authorize(
            context, ChannelPermission.PLAYER_MODIFIERS_READ, channel_twitch_id
        )
        user = self._find_player_viewer(channel.id, viewer)
        rows = (
            self.db.query(PlayerModifier)
            .filter(PlayerModifier.user_progress_id == user.id)
            .order_by(PlayerModifier.created_at.asc(), PlayerModifier.id.asc())
            .all()
        )
        return {
            "channel_twitch_id": channel.twitch_id,
            "user_twitch_id": user.user_twitch_id,
            "items": [self._serialize_player_modifier(row) for row in rows],
        }

    def set_player_modifier(
        self,
        context,
        channel_twitch_id: str,
        viewer: str,
        data: PlayerModifierSetRequest,
    ) -> dict[str, Any]:
        payload = data.model_dump(mode="json")

        def mutation() -> dict[str, Any]:
            channel, link = self._authorize(
                context,
                ChannelPermission.PLAYER_MODIFIERS_WRITE,
                channel_twitch_id,
                for_update=True,
            )
            user = self._find_player_viewer(channel.id, viewer, for_update=True)
            row = (
                self.db.query(PlayerModifier)
                .filter(
                    PlayerModifier.channel_id == channel.id,
                    PlayerModifier.user_progress_id == user.id,
                    PlayerModifier.stat_key == data.stat_key.value,
                    PlayerModifier.scope == data.scope.value,
                    PlayerModifier.source_key == data.source_key,
                )
                .with_for_update()
                .first()
            )
            before = self._serialize_player_modifier(row) if row else {}
            if row:
                if data.expected_version is None:
                    raise ApiProblem(
                        409,
                        "CONFIG_VERSION_CONFLICT",
                        "expected_version is required when updating a modifier",
                    )
                self._check_version(row.version, data.expected_version, context)
                row.version += 1
            else:
                if data.expected_version is not None:
                    raise ApiProblem(
                        409,
                        "CONFIG_VERSION_CONFLICT",
                        "Modifier does not exist",
                    )
                row = PlayerModifier(
                    id=str(uuid.uuid4()),
                    channel_id=channel.id,
                    user_progress_id=user.id,
                    stat_key=data.stat_key.value,
                    scope=data.scope.value,
                    source_key=data.source_key,
                    created_by_twitch_id=link.twitch_user_id,
                    created_by_discord_id=context.discord_user_id,
                )
                self.db.add(row)
            row.operation = data.operation.value
            row.value = data.value
            row.reason = data.reason
            row.starts_at = data.starts_at
            row.expires_at = data.expires_at
            row.is_enabled = True
            self.db.flush()
            after = self._serialize_player_modifier(row)
            self._audit(
                context,
                link.twitch_user_id,
                "player_modifier.set",
                "player_modifier",
                row.id,
                before,
                after,
            )
            return after

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "player_modifier.set",
            payload,
            context.request_id,
            mutation,
        )

    def set_player_modifier_state(
        self,
        context,
        channel_twitch_id: str,
        viewer: str,
        modifier_id: str,
        data: VersionedStateRequest,
    ) -> dict[str, Any]:
        def mutation() -> dict[str, Any]:
            channel, link = self._authorize(
                context, ChannelPermission.PLAYER_MODIFIERS_WRITE, channel_twitch_id
            )
            user = self._find_player_viewer(channel.id, viewer)
            row = self._find_player_modifier(user.id, modifier_id, for_update=True)
            self._check_version(row.version, data.expected_version, context)
            before = self._serialize_player_modifier(row)
            row.is_enabled = data.is_enabled
            row.version += 1
            self.db.flush()
            after = self._serialize_player_modifier(row)
            self._audit(
                context,
                link.twitch_user_id,
                "player_modifier.state",
                "player_modifier",
                row.id,
                before,
                after,
            )
            return after

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "player_modifier.state",
            data.model_dump(mode="json"),
            context.request_id,
            mutation,
        )

    def remove_player_modifier(
        self,
        context,
        channel_twitch_id: str,
        viewer: str,
        modifier_id: str,
        expected_version: int,
    ) -> dict[str, Any]:
        def mutation() -> dict[str, Any]:
            channel, link = self._authorize(
                context, ChannelPermission.PLAYER_MODIFIERS_WRITE, channel_twitch_id
            )
            user = self._find_player_viewer(channel.id, viewer)
            row = self._find_player_modifier(user.id, modifier_id, for_update=True)
            self._check_version(row.version, expected_version, context)
            before = self._serialize_player_modifier(row)
            self.db.delete(row)
            self.db.flush()
            self._audit(
                context,
                link.twitch_user_id,
                "player_modifier.remove",
                "player_modifier",
                row.id,
                before,
                {},
            )
            return {"status": "removed", "id": modifier_id}

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "player_modifier.remove",
            {"modifier_id": modifier_id, "expected_version": expected_version},
            context.request_id,
            mutation,
        )

    def explain_player_stats(
        self,
        context,
        channel_twitch_id: str,
        viewer: str,
        scope: ModifierScope,
    ) -> dict[str, Any]:
        channel, _ = self._authorize(
            context, ChannelPermission.PLAYER_MODIFIERS_READ, channel_twitch_id
        )
        user = self._find_player_viewer(channel.id, viewer)
        resolved = PlayerModifierService(self.db).resolve(user, scope)
        return {
            "channel_twitch_id": channel.twitch_id,
            "user_twitch_id": user.user_twitch_id,
            "scope": scope.value,
            "stats": resolved.explain(),
            "behavioral_effects": list(resolved.effects),
        }

    def list_items(self, context, channel_twitch_id: str, include_archived: bool) -> dict:
        channel, _ = self._authorize(context, ChannelPermission.ITEMS_READ, channel_twitch_id)
        query = self.db.query(ItemDefinition).filter(ItemDefinition.channel_id == channel.id)
        if not include_archived:
            query = query.filter(ItemDefinition.is_active.is_(True))
        rows = query.order_by(ItemDefinition.item_id.asc()).all()
        return {"items": [self._serialize_item_definition(row, channel) for row in rows]}

    def list_loot_tables(self, context, channel_twitch_id: str) -> dict:
        """List the channel's loot tables for entity-referencing effects.

        Loot tables are part of the item subsystem, so the read is guarded by
        the same permission as item reads.
        """
        channel, _ = self._authorize(context, ChannelPermission.ITEMS_READ, channel_twitch_id)
        rows = (
            self.db.query(LootTable)
            .filter(LootTable.channel_id == channel.id, LootTable.is_active.is_(True))
            .order_by(LootTable.title.asc(), LootTable.table_id.asc())
            .all()
        )
        return {
            "items": [
                {
                    "table_id": row.table_id,
                    "title": row.title,
                    "is_active": row.is_active,
                    "version": row.version,
                }
                for row in rows
            ]
        }

    def get_item(self, context, channel_twitch_id: str, item_id: str) -> dict:
        channel, _ = self._authorize(context, ChannelPermission.ITEMS_READ, channel_twitch_id)
        row = self._find_item_definition(channel.id, item_id)
        return self._serialize_item_definition(row, channel)

    def upsert_item(
        self,
        context,
        channel_twitch_id: str,
        data: DiscordItemUpsertRequest,
    ) -> dict:
        def mutation() -> dict:
            channel, link = self._authorize(
                context, ChannelPermission.ITEMS_WRITE, channel_twitch_id, for_update=True
            )
            existing = (
                self.db.query(ItemDefinition)
                .filter(
                    ItemDefinition.channel_id == channel.id,
                    ItemDefinition.item_id == data.item_id,
                )
                .with_for_update(of=ItemDefinition)
                .first()
            )
            before = self._serialize_item_definition(existing, channel) if existing else {}
            row = self.channel_repo.upsert_item_definition(
                channel_twitch_id=channel.twitch_id,
                item_id=data.item_id,
                title=data.title,
                item_type=data.item_type.value,
                slot=data.equipment_slot.value if data.equipment_slot else None,
                description=data.description,
                rarity=data.rarity.value,
                max_durability=data.max_durability,
                max_charges=data.max_charges,
                break_policy=data.break_policy.value,
                stack_size=data.stack_size,
                image_url=data.image_url,
                effects=[effect.model_dump(mode="json") for effect in data.effects],
                schema_version=data.schema_version,
                value=data.value,
                expected_version=data.expected_version,
                updated_by=link.twitch_user_id,
            )
            after = self._serialize_item_definition(row, channel)
            self._audit(
                context,
                link.twitch_user_id,
                "item.upsert",
                "item_definition",
                row.id,
                before,
                after,
            )
            return after

        def mutation_guarded() -> dict:
            try:
                return mutation()
            except ValueError as error:
                # Re-submitting a create for an item that already exists (or a
                # stale version) is a conflict for the admin, not a 500.
                raise ApiProblem(409, "ITEM_VERSION_CONFLICT", str(error))

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "item.upsert",
            data.model_dump(mode="json"),
            context.request_id,
            mutation_guarded,
        )

    def archive_item(
        self, context, channel_twitch_id: str, item_id: str, expected_version: int
    ) -> dict:
        def mutation() -> dict:
            channel, link = self._authorize(
                context, ChannelPermission.ITEMS_WRITE, channel_twitch_id
            )
            row = self._find_item_definition(
                channel.id, item_id, for_update=True
            )
            self._check_version(row.version, expected_version, context)
            before = self._serialize_item_definition(row, channel)
            row.is_active = False
            row.archived_at = datetime.now(timezone.utc)
            row.updated_by = link.twitch_user_id
            row.version += 1
            self.db.flush()
            after = self._serialize_item_definition(row, channel)
            self._audit(
                context,
                link.twitch_user_id,
                "item.archive",
                "item_definition",
                row.id,
                before,
                after,
            )
            return after

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "item.archive",
            {"item_id": item_id, "expected_version": expected_version},
            context.request_id,
            mutation,
        )

    def _ensure_pool_loot_table(self, pool) -> LootTable:
        """Return (creating if needed) the unified loot table for a pool.

        Legacy location_items rows are copied into the loot table exactly once
        so the admin editor can operate exclusively on the unified schema.
        """
        if pool.item_loot_table_id is not None:
            table = (
                self.db.query(LootTable)
                .filter(LootTable.id == pool.item_loot_table_id)
                .first()
            )
            if table is not None:
                return table
        table = LootTable(
            channel_id=pool.channel_id,
            table_id=f"pool-{pool.id}",
            title=pool.location_name or pool.location_id,
            version=1,
            is_active=True,
        )
        self.db.add(table)
        self.db.flush()
        pool.item_loot_table_id = table.id
        self.db.flush()
        return table

    def _item_drop_rows(self, pool) -> list:
        table = self._ensure_pool_loot_table(pool)
        return (
            self.db.query(LootTableEntry)
            .filter(
                LootTableEntry.loot_table_id == table.id,
                LootTableEntry.item_definition_id.isnot(None),
            )
            .order_by(LootTableEntry.id.asc())
            .all()
        )

    def preview_item_drop(
        self,
        context,
        channel_twitch_id: str,
        location_id: str,
        item_weight: int,
        item_id: str | None = None,
    ) -> dict:
        """Compute the runtime drop probability for a prospective item weight.

        The displayed values come from the backend calculation so the shown
        chance matches runtime selection (audit §10). Derived statistics
        (p50/p90 and expected active time at the standard cooldowns) are also
        computed here so Discord only formats them.

        When ``item_id`` is supplied (edit flow) the existing weight of that
        item is replaced instead of added, so the preview reflects the pool
        after the edit.
        """
        pool, _, _ = self._resolve_pool(
            context, channel_twitch_id, location_id, ChannelPermission.ITEMS_READ
        )
        rows = self._item_drop_rows(pool)
        proposed_weight = max(int(item_weight), 1)
        existing_weight = 0
        if item_id:
            existing = next(
                (row for row in rows if row.definition.item_id == item_id), None
            )
            if existing is not None:
                existing_weight = int(existing.weight)
        total_weight = (
            sum(int(row.weight) for row in rows) - existing_weight + proposed_weight
        )
        if total_weight <= 0:
            probability = 0.0
        else:
            probability = float(pool.items_drop_rate or 0.0) * (
                proposed_weight / total_weight
            )
        probability = round(probability, 6)
        selection_weight_share = (
            round(proposed_weight / total_weight, 6) if total_weight > 0 else 0.0
        )
        if probability > 0:
            expected, p50, p90 = geometric_first_success_stats(
                Decimal(str(probability))
            )
            expected_casts = float(expected)
            expected_active_time_minutes = {
                str(cooldown): round(expected_casts * float(cooldown), 1)
                for cooldown in DROP_PREVIEW_COOLDOWNS
            }
        else:
            expected_casts = None
            p50 = None
            p90 = None
            expected_active_time_minutes = None
        return {
            "location_id": pool.location_id,
            "items_drop_rate": pool.items_drop_rate,
            "proposed_weight": proposed_weight,
            "total_weight": total_weight,
            "selection_weight_share": selection_weight_share,
            "drop_probability": probability,
            "expected_casts_to_drop": expected_casts,
            "p50": p50,
            "p90": p90,
            "expected_active_time_minutes": expected_active_time_minutes,
        }

    def list_item_drops(
        self, context, channel_twitch_id: str, location_id: str
    ) -> dict:
        pool, _, _ = self._resolve_pool(
            context, channel_twitch_id, location_id, ChannelPermission.ITEMS_READ
        )
        rows = self._item_drop_rows(pool)
        return {
            "location_id": pool.location_id,
            "items": self._serialize_item_drops_with_chance(rows, pool),
        }

    def _serialize_item_drops_with_chance(self, rows, pool) -> list[dict]:
        """Serialize item drops and include the per-cast drop probability.

        Probability is derived from the same weighted pool used at runtime so the
        displayed chance always matches the backend calculation (audit §10).
        """
        total_weight = sum(int(row.weight) for row in rows) or 0
        items = []
        for row in rows:
            entry = self._serialize_item_drop(row, db=self.db)
            if total_weight > 0:
                entry["selection_weight_share"] = round(
                    int(row.weight) / total_weight, 6
                )
            else:
                entry["selection_weight_share"] = 0.0
            entry["drop_probability"] = round(
                float(pool.items_drop_rate or 0.0) * float(entry["selection_weight_share"]),
                6,
            )
            if entry["drop_probability"] > 0:
                entry["expected_casts_to_drop"] = round(1.0 / entry["drop_probability"], 1)
            else:
                entry["expected_casts_to_drop"] = None
            items.append(entry)
        return items

    def upsert_item_drop(
        self,
        context,
        channel_twitch_id: str,
        location_id: str,
        data: ItemDropUpsertRequest,
    ) -> dict:
        def mutation() -> dict:
            pool, channel, link = self._resolve_pool(
                context,
                channel_twitch_id,
                location_id,
                ChannelPermission.ITEM_DROPS_WRITE,
                for_update=True,
            )
            definition = self._find_item_definition(channel.id, data.item_id)
            if not definition.is_active:
                raise ApiProblem(422, "VALIDATION_ERROR", "Archived items cannot be dropped")
            table = self._ensure_pool_loot_table(pool)
            row = (
                self.db.query(LootTableEntry)
                .filter(
                    LootTableEntry.loot_table_id == table.id,
                    LootTableEntry.item_definition_id == definition.id,
                )
                .with_for_update(of=LootTableEntry)
                .first()
            )
            before = self._serialize_item_drop(row, db=self.db) if row else {}
            if row:
                if data.expected_version is None:
                    raise ApiProblem(
                        409,
                        "ITEM_DROP_EXISTS",
                        "Item drop already exists for this location; "
                        "use the item-drop edit command to change it",
                    )
                self._check_version(row.version, data.expected_version, context)
                row.version += 1
            else:
                if data.expected_version is not None:
                    raise ApiProblem(409, "CONFIG_VERSION_CONFLICT", "Item drop does not exist")
                row = LootTableEntry(
                    channel_id=pool.channel_id,
                    loot_table_id=table.id,
                    item_definition_id=definition.id,
                    weight=data.weight,
                    min_quantity=1,
                    max_quantity=1,
                    xp_gain=data.xp_gain,
                    message=data.message,
                    config_version=1,
                )
                self.db.add(row)
                self.db.flush()
            row.weight = data.weight
            row.xp_gain = data.xp_gain
            row.message = data.message
            stock = (
                self.db.query(LootTableEntryStock)
                .filter(LootTableEntryStock.loot_table_entry_id == row.id)
                .with_for_update(of=LootTableEntryStock)
                .first()
            )
            if data.quantity is None:
                if stock is not None:
                    self.db.delete(stock)
            else:
                if stock is None:
                    stock = LootTableEntryStock(
                        loot_table_entry_id=row.id,
                        remaining_quantity=int(data.quantity),
                        version=1,
                    )
                    self.db.add(stock)
                else:
                    stock.remaining_quantity = int(data.quantity)
                    stock.version += 1
            self.db.flush()
            after = self._serialize_item_drop(row, db=self.db)
            self._audit(
                context,
                link.twitch_user_id,
                "item_drop.upsert",
                "loot_table_entry",
                row.id,
                before,
                {**after, "channel_twitch_id": channel.twitch_id},
            )
            return after

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "item_drop.upsert",
            data.model_dump(mode="json"),
            context.request_id,
            mutation,
        )

    def remove_item_drop(
        self,
        context,
        channel_twitch_id: str,
        location_id: str,
        item_id: str,
        expected_version: int,
    ) -> dict:
        def mutation() -> dict:
            pool, channel, link = self._resolve_pool(
                context,
                channel_twitch_id,
                location_id,
                ChannelPermission.ITEM_DROPS_WRITE,
            )
            definition = self._find_item_definition(channel.id, item_id)
            table = self._ensure_pool_loot_table(pool)
            row = (
                self.db.query(LootTableEntry)
                .filter(
                    LootTableEntry.loot_table_id == table.id,
                    LootTableEntry.item_definition_id == definition.id,
                )
                .with_for_update(of=LootTableEntry)
                .first()
            )
            if not row:
                raise ApiProblem(404, "ITEM_DROP_NOT_FOUND", "Item drop not found")
            self._check_version(row.version, expected_version, context)
            before = self._serialize_item_drop(row, db=self.db)
            self.db.delete(row)
            self.db.flush()
            self._audit(
                context,
                link.twitch_user_id,
                "item_drop.remove",
                "loot_table_entry",
                row.id,
                {**before, "channel_twitch_id": channel.twitch_id},
                {},
            )
            return {"status": "removed", "item_id": item_id}

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "item_drop.remove",
            {"item_id": item_id, "expected_version": expected_version},
            context.request_id,
            mutation,
        )

    def get_player_inventory_admin(
        self, context, channel_twitch_id: str, viewer: str
    ) -> dict:
        channel, _ = self._authorize(
            context, ChannelPermission.PLAYER_INVENTORY_READ, channel_twitch_id
        )
        user = self._find_player_viewer(channel.id, viewer)
        response = InventoryService(UserRepository(self.db)).get_inventory_msg(
            user.user_twitch_id, channel.twitch_id
        )
        return response.model_dump(mode="json")

    def grant_player_item(
        self,
        context,
        channel_twitch_id: str,
        viewer: str,
        data: PlayerItemGrantRequest,
    ) -> dict:
        def mutation() -> dict:
            channel, link = self._authorize(
                context, ChannelPermission.PLAYER_ITEMS_GRANT, channel_twitch_id
            )
            user = self._find_player_viewer(channel.id, viewer)
            slot_bonus = PlayerModifierService(self.db).inventory_slot_bonus(user)
            items = InventoryRepository(
                self.db, max_slots_add=slot_bonus
            ).grant_many(
                user, [data.model_dump(mode="python")]
            )
            after = [self._serialize_inventory_item(row) for row in items]
            self._audit(
                context,
                link.twitch_user_id,
                "player.item_grant",
                "inventory_item",
                ",".join(str(row.id) for row in items),
                {},
                {"channel_twitch_id": channel.twitch_id, "items": after},
            )
            return {"items": after}

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "player.item_grant",
            data.model_dump(mode="json"),
            context.request_id,
            mutation,
        )

    def revoke_player_item(
        self,
        context,
        channel_twitch_id: str,
        viewer: str,
        inventory_item_id: int,
        data: PlayerItemRevokeRequest,
    ) -> dict:
        def mutation() -> dict:
            channel, link = self._authorize(
                context, ChannelPermission.PLAYER_ITEMS_GRANT, channel_twitch_id
            )
            user = self._find_player_viewer(channel.id, viewer)
            row = (
                self.db.query(InventoryItem)
                .filter(
                    InventoryItem.id == inventory_item_id,
                    InventoryItem.user_id == user.id,
                )
                .with_for_update(of=InventoryItem)
                .first()
            )
            if not row:
                raise ApiProblem(404, "INVENTORY_ITEM_NOT_FOUND", "Inventory item not found")
            self._check_version(row.version, data.expected_version, context)
            before = self._serialize_inventory_item(row)
            if data.quantity > row.quantity:
                raise ApiProblem(422, "VALIDATION_ERROR", "Revoke quantity exceeds inventory")
            row.quantity -= data.quantity
            if row.quantity == 0:
                self.db.delete(row)
                after = {}
            else:
                row.version += 1
                after = self._serialize_inventory_item(row)
            self.db.flush()
            self._audit(
                context,
                link.twitch_user_id,
                "player.item_revoke",
                "inventory_item",
                inventory_item_id,
                {**before, "channel_twitch_id": channel.twitch_id},
                after,
            )
            return {"status": "revoked", "remaining": row.quantity if after else 0}

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "player.item_revoke",
            data.model_dump(mode="json"),
            context.request_id,
            mutation,
        )

    def get_config(self, context: DiscordServiceContext, channel_twitch_id: str) -> dict[str, Any]:
        channel, _ = self._authorize(context, ChannelPermission.CONFIG_READ, channel_twitch_id)
        overrides = dict((channel.config or {}).get("custom_params", {}))
        effective = GameConfig.model_validate(overrides).model_dump(mode="json")
        defaults = GameConfig().model_dump(mode="json")
        return {
            "channel_twitch_id": channel.twitch_id,
            "version": channel.config_version,
            "defaults": defaults,
            "overrides": overrides,
            "effective": effective,
            "updated_at": channel.config_updated_at.isoformat(),
        }

    def get_messages(self, context, channel_twitch_id: str) -> dict[str, Any]:
        channel, _ = self._authorize(context, ChannelPermission.CONFIG_READ, channel_twitch_id)
        custom_messages = dict((channel.config or {}).get("messages") or {})
        items = []
        for entry in message_placeholder_catalog():
            message_key = entry["message_key"]
            custom_message = custom_messages.get(message_key)
            items.append(
                {
                    **entry,
                    "custom_message": custom_message,
                    "effective_message": custom_message or entry["default_message"],
                }
            )
        return {"version": channel.config_version, "items": items}

    def patch_message(
        self,
        context,
        channel_twitch_id: str,
        message_key: str,
        data: MessageTemplatePatchRequest,
    ) -> dict[str, Any]:
        normalized_template = data.template.strip() if data.template else None
        try:
            validate_custom_message_template(message_key, normalized_template or "")
        except ValueError as error:
            raise ApiProblem(422, "VALIDATION_ERROR", str(error)) from error

        payload = {
            "expected_version": data.expected_version,
            "message_key": message_key,
            "template": normalized_template,
        }

        def mutation() -> dict[str, Any]:
            channel, link = self._authorize(
                context,
                ChannelPermission.CONFIG_WRITE,
                channel_twitch_id,
                for_update=True,
            )
            self._check_version(channel.config_version, data.expected_version, context)
            config = dict(channel.config or {})
            messages = dict(config.get("messages") or {})
            before = messages.get(message_key)
            if normalized_template:
                messages[message_key] = normalized_template
            else:
                messages.pop(message_key, None)
            if before == messages.get(message_key):
                return {
                    "version": channel.config_version,
                    "message_key": message_key,
                    "custom_message": before,
                }
            config["messages"] = messages
            channel.config = config
            channel.config_version += 1
            channel.config_updated_at = datetime.now(timezone.utc)
            self.db.flush()
            self._audit(
                context,
                link.twitch_user_id,
                "message.patch",
                "message",
                message_key,
                {"template": before},
                {"template": normalized_template},
            )
            return {
                "version": channel.config_version,
                "message_key": message_key,
                "custom_message": normalized_template,
            }

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "message.patch",
            payload,
            context.request_id,
            mutation,
        )

    def patch_config(
        self,
        context: DiscordServiceContext,
        channel_twitch_id: str,
        data: ConfigPatchRequest,
    ) -> dict[str, Any]:
        payload = data.model_dump(mode="json", exclude_none=True)

        def mutation() -> dict[str, Any]:
            channel, link = self._authorize(
                context, ChannelPermission.CONFIG_WRITE, channel_twitch_id, for_update=True
            )
            self._check_version(channel.config_version, data.expected_version, context)
            config = dict(channel.config or {})
            before = dict(config.get("custom_params", {}))
            changes = data.changes.model_dump(mode="json", exclude_none=True)
            merged = {**before, **changes}
            effective = GameConfig.model_validate(merged).model_dump(mode="json")
            if not changes or all(before.get(key) == value for key, value in changes.items()):
                return {
                    "version": channel.config_version,
                    "changed_fields": [],
                    "effective": effective,
                }
            config["custom_params"] = merged
            channel.config = config
            channel.config_version += 1
            channel.config_updated_at = datetime.now(timezone.utc)
            flag_modified(channel, "config")
            self.db.flush()
            self._audit(
                context,
                link.twitch_user_id,
                "config.patch",
                "channel_config",
                str(channel.id),
                before,
                merged,
            )
            return {
                "version": channel.config_version,
                "changed_fields": sorted(changes),
                "effective": effective,
            }

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "config.patch",
            payload,
            context.request_id,
            mutation,
        )

    def reset_config(
        self,
        context: DiscordServiceContext,
        channel_twitch_id: str,
        data: ConfigResetRequest,
    ) -> dict[str, Any]:
        if data.section not in CONFIG_SECTIONS:
            raise ApiProblem(422, "VALIDATION_ERROR", "Unknown config section")

        def mutation() -> dict[str, Any]:
            channel, link = self._authorize(
                context, ChannelPermission.CONFIG_WRITE, channel_twitch_id, for_update=True
            )
            self._check_version(channel.config_version, data.expected_version, context)
            config = dict(channel.config or {})
            before = dict(config.get("custom_params", {}))
            after = {
                key: value
                for key, value in before.items()
                if key not in CONFIG_SECTIONS[data.section]
            }
            if after == before:
                return self.get_config(context, channel_twitch_id)
            config["custom_params"] = after
            channel.config = config
            channel.config_version += 1
            channel.config_updated_at = datetime.now(timezone.utc)
            flag_modified(channel, "config")
            self.db.flush()
            self._audit(
                context,
                link.twitch_user_id,
                "config.reset",
                "channel_config",
                str(channel.id),
                before,
                after,
            )
            return self.get_config(context, channel_twitch_id)

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "config.reset",
            data.model_dump(mode="json"),
            context.request_id,
            mutation,
        )

    def list_locations(
        self, context: DiscordServiceContext, channel_twitch_id: str
    ) -> dict[str, Any]:
        channel, _ = self._authorize(context, ChannelPermission.CONFIG_READ, channel_twitch_id)
        pools = (
            self.db.query(RewardPool)
            .filter(RewardPool.channel_id == channel.id)
            .order_by(RewardPool.location_id)
            .limit(50)
            .all()
        )
        return {"items": [self._serialize_location(pool) for pool in pools], "total": len(pools)}

    def get_location(
        self,
        context: DiscordServiceContext,
        channel_twitch_id: str,
        location_id: str,
    ) -> dict[str, Any]:
        pool, _channel, _link = self._resolve_pool(context, channel_twitch_id, location_id)
        return self._serialize_location(pool, include_rewards=True)

    def create_location(
        self,
        context: DiscordServiceContext,
        channel_twitch_id: str,
        data: LocationCreateRequest,
    ) -> dict[str, Any]:
        def mutation() -> dict[str, Any]:
            channel, link = self._authorize(
                context, ChannelPermission.LOCATIONS_WRITE, channel_twitch_id, for_update=True
            )
            if self.db.query(RewardPool).filter(RewardPool.channel_id == channel.id).count() >= 50:
                raise ApiProblem(422, "VALIDATION_ERROR", "Location limit reached")
            if self._find_pool(channel.id, data.location_id):
                raise ApiProblem(409, "VALIDATION_ERROR", "Location ID already exists")
            pool = RewardPool(
                channel_id=channel.id,
                location_id=data.location_id,
                location_name=data.location_name,
                items_drop_rate=float(data.items_drop_rate),
                requirements=data.requirements.model_dump(mode="json", exclude_none=True),
                rewards_data=[],
            )
            self.db.add(pool)
            self.db.flush()
            after = self._serialize_location(pool)
            self._audit(
                context, link.twitch_user_id, "location.create", "location", str(pool.id), {}, after
            )
            return after

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "location.create",
            data.model_dump(mode="json"),
            context.request_id,
            mutation,
        )

    def patch_location(
        self,
        context: DiscordServiceContext,
        channel_twitch_id: str,
        location_id: str,
        data: LocationPatchRequest,
    ) -> dict[str, Any]:
        def mutation() -> dict[str, Any]:
            pool, _channel, link = self._resolve_pool(
                context,
                channel_twitch_id,
                location_id,
                ChannelPermission.LOCATIONS_WRITE,
                for_update=True,
            )
            self._check_version(pool.version, data.expected_version, context)
            before = self._serialize_location(pool)
            if data.location_name is not None:
                pool.location_name = data.location_name
            if data.items_drop_rate is not None:
                pool.items_drop_rate = float(data.items_drop_rate)
            if data.requirements is not None:
                pool.requirements = data.requirements.model_dump(mode="json", exclude_none=True)
            pool.version += 1
            self.db.flush()
            after = self._serialize_location(pool)
            self._audit(
                context,
                link.twitch_user_id,
                "location.patch",
                "location",
                str(pool.id),
                before,
                after,
            )
            return after

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "location.patch",
            data.model_dump(mode="json", exclude_none=True),
            context.request_id,
            mutation,
        )

    def delete_location(
        self,
        context: DiscordServiceContext,
        channel_twitch_id: str,
        location_id: str,
    ) -> dict[str, Any]:
        if location_id == "default":
            raise ApiProblem(409, "LOCATION_IN_USE", "Default location cannot be deleted")

        def mutation() -> dict[str, Any]:
            pool, channel, link = self._resolve_pool(
                context,
                channel_twitch_id,
                location_id,
                ChannelPermission.LOCATIONS_WRITE,
                for_update=True,
            )
            in_event = (
                self.db.query(FishingEvent)
                .filter(
                    FishingEvent.channel_id == channel.id,
                    FishingEvent.is_active.is_(True),
                    FishingEvent.override_loot_pool == location_id,
                )
                .first()
            )
            players = (
                self.db.query(UserProgress)
                .filter(
                    UserProgress.channel_id == channel.id,
                    UserProgress.current_location_id == location_id,
                )
                .first()
            )
            if in_event or players:
                raise ApiProblem(409, "LOCATION_IN_USE", "Location is currently in use")
            before = self._serialize_location(pool, include_rewards=True)
            self.db.delete(pool)
            self.db.flush()
            self._audit(
                context,
                link.twitch_user_id,
                "location.delete",
                "location",
                str(pool.id),
                before,
                {},
            )
            return {"status": "deleted", "location_id": location_id}

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "location.delete",
            {"location_id": location_id},
            context.request_id,
            mutation,
        )

    def list_rewards(self, context, channel_twitch_id: str, location_id: str) -> dict[str, Any]:
        pool, _channel, _link = self._resolve_pool(context, channel_twitch_id, location_id)
        rewards = self._normalized_rewards(pool)
        total_weight = sum(int(item["weight"]) for item in rewards)
        return {
            "version": pool.version,
            "items": [
                {**item, "probability": (int(item["weight"]) / total_weight if total_weight else 0)}
                for item in rewards
            ],
        }

    def create_reward(self, context, channel_twitch_id, location_id, data: RewardCreateRequest):
        return self._mutate_reward(context, channel_twitch_id, location_id, data, "create")

    def patch_reward(
        self, context, channel_twitch_id, location_id, reward_id, data: RewardPatchRequest
    ):
        return self._mutate_reward(
            context, channel_twitch_id, location_id, data, "patch", reward_id
        )

    def import_legacy_rewards(
        self,
        context,
        channel_twitch_id: str,
        location_id: str,
        data: LegacyRewardImportRequest,
    ) -> dict[str, Any]:
        if data.dry_run:
            pool, _channel, _link = self._resolve_pool(
                context, channel_twitch_id, location_id, ChannelPermission.CONFIG_READ
            )
            self._check_version(pool.version, data.expected_version, context)
            current = self._normalized_rewards(pool)
            try:
                result = convert_legacy_rewards(data.payload)
            except ValueError as error:
                raise ApiProblem(422, "LEGACY_IMPORT_INVALID", str(error)) from error
            final_count = len(result.rewards) if data.replace_existing else len(current) + len(
                result.rewards
            )
            if final_count > 100:
                raise ApiProblem(422, "VALIDATION_ERROR", "Reward limit would be exceeded")
            return self._legacy_import_response(pool.version, final_count, result, True)

        payload = data.model_dump(mode="json")

        def mutation() -> dict[str, Any]:
            pool, _channel, link = self._resolve_pool(
                context,
                channel_twitch_id,
                location_id,
                ChannelPermission.REWARDS_WRITE,
                for_update=True,
            )
            self._check_version(pool.version, data.expected_version, context)
            current = self._normalized_rewards(pool)
            try:
                result = convert_legacy_rewards(data.payload)
            except ValueError as error:
                raise ApiProblem(422, "LEGACY_IMPORT_INVALID", str(error)) from error
            rewards = result.rewards if data.replace_existing else [*current, *result.rewards]
            if len(rewards) > 100:
                raise ApiProblem(422, "VALIDATION_ERROR", "Reward limit would be exceeded")
            if len({item["reward_id"] for item in rewards}) != len(rewards):
                raise ApiProblem(409, "REWARD_ID_CONFLICT", "Imported reward ID already exists")
            before_count = len(current)
            pool.rewards_data = rewards
            pool.version += 1
            flag_modified(pool, "rewards_data")
            self.db.flush()
            self._audit(
                context,
                link.twitch_user_id,
                "reward.import_legacy",
                "reward_pool",
                str(pool.id),
                {"reward_count": before_count},
                {
                    "reward_count": len(rewards),
                    "imported_count": len(result.rewards),
                    "source_counts": result.source_counts,
                    "target_counts": result.target_counts,
                },
            )
            return self._legacy_import_response(pool.version, len(rewards), result, False)

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "reward.import_legacy",
            payload,
            context.request_id,
            mutation,
        )

    def delete_reward(
        self, context, channel_twitch_id, location_id, reward_id, expected_version: int
    ):
        data = {"expected_version": expected_version, "reward_id": reward_id}

        def mutation() -> dict[str, Any]:
            pool, _channel, link = self._resolve_pool(
                context,
                channel_twitch_id,
                location_id,
                ChannelPermission.REWARDS_WRITE,
                for_update=True,
            )
            self._check_version(pool.version, expected_version, context)
            rewards = self._normalized_rewards(pool)
            target = next((item for item in rewards if item["reward_id"] == reward_id), None)
            if not target:
                raise ApiProblem(404, "REWARD_NOT_FOUND", "Reward not found")
            pool.rewards_data = [item for item in rewards if item["reward_id"] != reward_id]
            pool.version += 1
            flag_modified(pool, "rewards_data")
            self.db.flush()
            self._audit(
                context, link.twitch_user_id, "reward.delete", "reward", reward_id, target, {}
            )
            return {"status": "deleted", "reward_id": reward_id, "version": pool.version}

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "reward.delete",
            data,
            context.request_id,
            mutation,
        )

    def list_events(self, context, channel_twitch_id):
        channel, _ = self._authorize(context, ChannelPermission.CONFIG_READ, channel_twitch_id)
        events = self.channel_repo.list_fishing_events(channel.id)
        return {"items": [self._serialize_event(event) for event in events]}

    def get_event(self, context, channel_twitch_id, event_id):
        channel, _ = self._authorize(context, ChannelPermission.CONFIG_READ, channel_twitch_id)
        event = self.channel_repo.get_fishing_event(channel.id, event_id)
        if not event:
            raise ApiProblem(404, "EVENT_NOT_FOUND", "Event not found")
        return self._serialize_event(event)

    def create_event(self, context, channel_twitch_id, data: DiscordEventCreateRequest):
        def mutation():
            channel, link = self._authorize(
                context, ChannelPermission.EVENTS_WRITE, channel_twitch_id, for_update=True
            )
            self._validate_event_location(channel.id, data.override_loot_pool)
            event = FishingEvent(
                channel_id=channel.id,
                event_title=data.event_title,
                modifiers=data.modifiers.model_dump(mode="json"),
                override_loot_pool=data.override_loot_pool,
                is_active=False,
            )
            self.db.add(event)
            self.db.flush()
            after = self._serialize_event(event)
            self._audit(
                context, link.twitch_user_id, "event.create", "event", str(event.id), {}, after
            )
            return after

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "event.create",
            data.model_dump(mode="json"),
            context.request_id,
            mutation,
        )

    def patch_event(self, context, channel_twitch_id, event_id, data: DiscordEventPatchRequest):
        def mutation():
            channel, link = self._authorize(
                context, ChannelPermission.EVENTS_WRITE, channel_twitch_id, for_update=True
            )
            event = self._find_event(channel.id, event_id, for_update=True)
            if not event:
                raise ApiProblem(404, "EVENT_NOT_FOUND", "Event not found")
            self._check_version(event.version, data.expected_version, context)
            before = self._serialize_event(event)
            if data.event_title is not None:
                event.event_title = data.event_title
            if data.modifiers is not None:
                event.modifiers = data.modifiers.model_dump(mode="json")
                flag_modified(event, "modifiers")
                # An explicit v2 save from the owner confirms/reviews the event:
                # clear the unsafe-inheritance flag and pin the schema version.
                if data.modifiers.model_dump(mode="json").get("schema_version") == 2:
                    event.requires_review = False
                    event.modifier_schema_version = 2
                    history = list(event.modifiers_history or [])
                    history.append(
                        {
                            "reviewed_at": datetime.now(timezone.utc).isoformat(),
                            "modifiers_v2": data.modifiers.model_dump(mode="json"),
                        }
                    )
                    event.modifiers_history = history
                    flag_modified(event, "modifiers_history")
            if "override_loot_pool" in data.model_fields_set:
                self._validate_event_location(channel.id, data.override_loot_pool)
                event.override_loot_pool = data.override_loot_pool
            event.version += 1
            self.db.flush()
            after = self._serialize_event(event)
            self._audit(
                context, link.twitch_user_id, "event.patch", "event", str(event.id), before, after
            )
            return after

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "event.patch",
            data.model_dump(mode="json", exclude_none=True),
            context.request_id,
            mutation,
        )

    def start_event(self, context, channel_twitch_id, event_id, data: DiscordEventStartRequest):
        def mutation():
            channel, link = self._authorize(
                context, ChannelPermission.EVENTS_TOGGLE, channel_twitch_id, for_update=True
            )
            events = (
                self.db.query(FishingEvent)
                .filter(FishingEvent.channel_id == channel.id)
                .with_for_update()
                .all()
            )
            event = next((candidate for candidate in events if candidate.id == event_id), None)
            if not event:
                raise ApiProblem(404, "EVENT_NOT_FOUND", "Event not found")
            if event.requires_review:
                raise ApiProblem(
                    422,
                    "EVENT_REQUIRES_REVIEW",
                    "This event has unsafe inherited modifiers and must be reviewed "
                    "before it can be started again.",
                )
            self._check_version(event.version, data.expected_version, context)
            before = self._serialize_event(event)
            now = datetime.now(timezone.utc)
            for candidate in events:
                candidate.is_active = candidate.id == event.id
                if candidate.id == event.id:
                    candidate.version += 1
                    candidate.status = "active"
                    candidate.starts_at = now
                    candidate.activated_at = now
                    candidate.ends_at = (
                        now + timedelta(seconds=data.duration_seconds)
                        if data.duration_seconds
                        else None
                    )
                else:
                    candidate.status = "draft"
                    candidate.deactivated_at = now
            self.db.flush()
            scheduled = None
            if data.duration_seconds:
                scheduled = self.event_lifecycle.schedule_auto_disable(
                    channel.twitch_id,
                    channel.id,
                    event.id,
                    event.event_title,
                    data.duration_seconds,
                    link.twitch_user_id,
                )
            after = self._serialize_event(event)
            self._audit(
                context, link.twitch_user_id, "event.start", "event", str(event.id), before, after
            )
            return {
                "event": after,
                "scheduled_disable_at": scheduled.get("execute_at") if scheduled else None,
            }

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "event.start",
            {"event_id": event_id, **data.model_dump(mode="json")},
            context.request_id,
            mutation,
        )

    def stop_event(self, context, channel_twitch_id):
        def mutation():
            channel, link = self._authorize(
                context, ChannelPermission.EVENTS_TOGGLE, channel_twitch_id, for_update=True
            )
            event = (
                self.db.query(FishingEvent)
                .filter(FishingEvent.channel_id == channel.id, FishingEvent.is_active.is_(True))
                .with_for_update()
                .first()
            )
            if not event:
                return {"status": "no_active_event"}
            before = self._serialize_event(event)
            event.is_active = False
            event.status = "ended"
            event.deactivated_at = datetime.now(timezone.utc)
            event.ends_at = event.deactivated_at
            event.version += 1
            self.event_lifecycle.cancel_auto_disable(channel.twitch_id)
            self.db.flush()
            after = self._serialize_event(event)
            self._audit(
                context, link.twitch_user_id, "event.stop", "event", str(event.id), before, after
            )
            return {"status": "stopped", "event": after}

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "event.stop",
            {},
            context.request_id,
            mutation,
        )

    def delete_event(self, context, channel_twitch_id, event_id, expected_version):
        def mutation():
            channel, link = self._authorize(
                context, ChannelPermission.EVENTS_WRITE, channel_twitch_id, for_update=True
            )
            event = self._find_event(channel.id, event_id, for_update=True)
            if not event:
                raise ApiProblem(404, "EVENT_NOT_FOUND", "Event not found")
            self._check_version(event.version, expected_version, context)
            before = self._serialize_event(event)
            if event.is_active:
                self.event_lifecycle.cancel_auto_disable(channel.twitch_id)
            self.db.delete(event)
            self.db.flush()
            self._audit(
                context, link.twitch_user_id, "event.delete", "event", str(event.id), before, {}
            )
            return {"status": "deleted", "event_id": event_id}

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "event.delete",
            {"event_id": event_id, "expected_version": expected_version},
            context.request_id,
            mutation,
        )

    def _mutate_reward(self, context, channel_twitch_id, location_id, data, mode, reward_id=None):
        payload = data.model_dump(mode="json")

        def mutation() -> dict[str, Any]:
            pool, _channel, link = self._resolve_pool(
                context,
                channel_twitch_id,
                location_id,
                ChannelPermission.REWARDS_WRITE,
                for_update=True,
            )
            self._check_version(pool.version, data.expected_version, context)
            rewards = self._normalized_rewards(pool)
            normalized = data.reward.model_dump(mode="json")
            before = {}
            if mode == "create":
                if len(rewards) >= 100:
                    raise ApiProblem(422, "VALIDATION_ERROR", "Reward limit reached")
                rewards.append(normalized)
                action = "reward.create"
            else:
                target_index = next(
                    (index for index, item in enumerate(rewards) if item["reward_id"] == reward_id),
                    None,
                )
                if target_index is None:
                    raise ApiProblem(404, "REWARD_NOT_FOUND", "Reward not found")
                before = rewards[target_index]
                normalized["reward_id"] = reward_id
                rewards[target_index] = normalized
                action = "reward.patch"
            pool.rewards_data = rewards
            pool.version += 1
            flag_modified(pool, "rewards_data")
            self.db.flush()
            self._audit(
                context,
                link.twitch_user_id,
                action,
                "reward",
                normalized["reward_id"],
                before,
                normalized,
            )
            return {"reward": normalized, "version": pool.version}

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            f"reward.{mode}",
            payload,
            context.request_id,
            mutation,
        )

    def _find_item_definition(
        self, channel_id: int, item_id: str, *, for_update: bool = False
    ) -> ItemDefinition:
        query = self.db.query(ItemDefinition).filter(
            ItemDefinition.channel_id == channel_id,
            ItemDefinition.item_id == item_id,
        )
        if for_update:
            query = query.with_for_update(of=ItemDefinition)
        row = query.first()
        if not row:
            raise ApiProblem(404, "ITEM_NOT_FOUND", "Item definition not found")
        return row

    @staticmethod
    def _serialize_item_definition(row: ItemDefinition, channel: Channel) -> dict:
        return {
            "channel_twitch_id": channel.twitch_id,
            "id": row.id,
            "item_id": row.item_id,
            "title": row.title,
            "description": row.description,
            "item_type": row.type,
            "equipment_slot": row.slot,
            "rarity": row.rarity,
            "stack_size": row.stack_size,
            "max_durability": row.max_durability,
            "max_charges": row.max_charges,
            "break_policy": row.break_policy,
            "effects": row.effects or [],
            "schema_version": row.schema_version,
            "image_url": row.image_url,
            "value": str(row.value) if row.value is not None else None,
            "is_active": row.is_active,
            "version": row.version,
            "archived_at": row.archived_at.isoformat() if row.archived_at else None,
            "updated_at": row.updated_at.isoformat(),
            "updated_by": row.updated_by,
        }

    @staticmethod
    def _serialize_item_drop(row: LootTableEntry, db=None) -> dict:
        stock = None
        if db is not None:
            stock = (
                db.query(LootTableEntryStock)
                .filter(LootTableEntryStock.loot_table_entry_id == row.id)
                .first()
            )
        return {
            "item_id": row.definition.item_id,
            "title": row.definition.title,
            "weight": row.weight,
            "xp_gain": row.xp_gain,
            "quantity": stock.remaining_quantity if stock else None,
            "message": row.message,
            "effects": row.definition.effects or [],
            "version": row.version,
            "updated_at": row.updated_at.isoformat(),
        }

    @staticmethod
    def _serialize_inventory_item(row: InventoryItem) -> dict:
        return {
            "id": row.id,
            "item_id": row.definition.item_id,
            "title": row.definition.title,
            "slot_id": row.slot_id,
            "quantity": row.quantity,
            "current_durability": row.current_durability,
            "max_durability": row.definition.max_durability,
            "current_charges": row.current_charges,
            "max_charges": row.definition.max_charges,
            "definition_version": row.definition_version,
            "version": row.version,
            "meta": row.meta or {},
        }

    def _find_player(
        self, channel_id: int, user_twitch_id: str, *, for_update: bool = False
    ) -> UserProgress:
        query = self.db.query(UserProgress).filter(
            UserProgress.channel_id == channel_id,
            UserProgress.user_twitch_id == user_twitch_id,
        )
        if for_update:
            query = query.with_for_update(of=UserProgress)
        user = query.first()
        if not user:
            raise ApiProblem(404, "PLAYER_NOT_FOUND", "Player not found")
        return user

    def _find_player_viewer(
        self, channel_id: int, viewer: str, *, for_update: bool = False
    ) -> UserProgress:
        """Resolve an admin-supplied viewer to a player row.

        The owner types the viewer's Twitch username (case-insensitive exact
        match first); the legacy numeric twitch id keeps working as a fallback
        so existing links and scripts are not broken.
        """
        query = self.db.query(UserProgress).filter(
            UserProgress.channel_id == channel_id,
            UserProgress.username.ilike(viewer.strip()),
        )
        if for_update:
            query = query.with_for_update(of=UserProgress)
        user = query.first()
        if user is not None:
            return user
        return self._find_player(
            channel_id, viewer.strip(), for_update=for_update
        )

    def _find_player_modifier(
        self, user_id: int, modifier_id: str, *, for_update: bool = False
    ) -> PlayerModifier:
        query = self.db.query(PlayerModifier).filter(
            PlayerModifier.user_progress_id == user_id,
            PlayerModifier.id == modifier_id,
        )
        if for_update:
            query = query.with_for_update(of=PlayerModifier)
        row = query.first()
        if not row:
            raise ApiProblem(404, "PLAYER_MODIFIER_NOT_FOUND", "Player modifier not found")
        return row

    @staticmethod
    def _serialize_player_modifier(row: PlayerModifier) -> dict[str, Any]:
        return {
            "id": row.id,
            "stat_key": row.stat_key,
            "operation": row.operation,
            "value": str(row.value),
            "scope": row.scope,
            "source_key": row.source_key,
            "reason": row.reason,
            "starts_at": row.starts_at.isoformat() if row.starts_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "is_enabled": row.is_enabled,
            "version": row.version,
            "created_by_twitch_id": row.created_by_twitch_id,
            "created_by_discord_id": row.created_by_discord_id,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }

    def _authorize(self, context, permission, channel_twitch_id=None, *, for_update=False):
        link = self._get_link(context)
        binding = self._get_binding(context)
        channel = binding.channel
        if channel_twitch_id and channel.twitch_id != channel_twitch_id:
            raise ApiProblem(403, "PERMISSION_DENIED", "Guild is not bound to this channel")
        if link.twitch_user_id == channel.twitch_id:
            role = "owner"
        else:
            access = self.channel_repo.get_access_record(channel.id, link.twitch_user_id)
            role = access.role if access else None
        if not role or permission not in ROLE_PERMISSIONS.get(role, set()):
            raise ApiProblem(
                403, "PERMISSION_DENIED", "Permission denied", request_id=context.request_id
            )
        if for_update:
            channel = (
                self.db.query(Channel).filter(Channel.id == channel.id).with_for_update().one()
            )
        return channel, link

    def _get_link(self, context, required=True):
        link = (
            self.db.query(DiscordAccountLink)
            .filter(
                DiscordAccountLink.discord_user_id == context.discord_user_id,
                DiscordAccountLink.revoked_at.is_(None),
            )
            .first()
        )
        if not link and required:
            raise ApiProblem(403, "DISCORD_LINK_REQUIRED", "Link a Twitch account first")
        return link

    def _get_binding(self, context):
        if not context.discord_guild_id:
            raise ApiProblem(
                403, "GUILD_BINDING_REQUIRED", "This command is only available in a guild"
            )
        binding = (
            self.db.query(DiscordGuildBinding)
            .filter(DiscordGuildBinding.discord_guild_id == context.discord_guild_id)
            .first()
        )
        if not binding:
            raise ApiProblem(403, "GUILD_BINDING_REQUIRED", "Run /fish setup first")
        return binding

    def _resolve_pool(
        self,
        context,
        channel_twitch_id,
        location_id,
        permission=ChannelPermission.CONFIG_READ,
        *,
        for_update=False,
    ):
        channel, link = self._authorize(
            context,
            permission,
            channel_twitch_id,
            for_update=for_update,
        )
        pool = self._find_pool(channel.id, location_id, for_update=for_update)
        if not pool:
            raise ApiProblem(404, "LOCATION_NOT_FOUND", "Location not found")
        return pool, channel, link

    def _find_pool(self, channel_id, location_id, *, for_update=False):
        query = self.db.query(RewardPool).filter(
            RewardPool.channel_id == channel_id, RewardPool.location_id == location_id
        )
        if for_update:
            query = query.with_for_update()
        return query.first()

    def _find_event(self, channel_id, event_id, *, for_update=False):
        query = self.db.query(FishingEvent).filter(
            FishingEvent.channel_id == channel_id,
            FishingEvent.id == event_id,
        )
        if for_update:
            query = query.with_for_update()
        return query.first()

    def _normalized_rewards(self, pool):
        normalized = []
        changed = False
        for raw in list(pool.rewards_data or []):
            try:
                reward = REWARD_ADAPTER.validate_python(raw).model_dump(mode="json")
            except ValidationError as error:
                raise ApiProblem(422, "VALIDATION_ERROR", "Stored reward is invalid") from error
            normalized.append(reward)
            changed = changed or reward != raw
        if changed:
            pool.rewards_data = normalized
            flag_modified(pool, "rewards_data")
            self.db.flush()
        return normalized

    @staticmethod
    def _legacy_import_response(version, final_count, result, dry_run):
        return {
            "dry_run": dry_run,
            "version": version,
            "imported_count": len(result.rewards),
            "final_count": final_count,
            "source_counts": result.source_counts,
            "target_counts": result.target_counts,
            "warnings": result.warnings,
        }

    def _serialize_location(self, pool, include_rewards=False):
        data = {
            "location_id": pool.location_id,
            "location_name": pool.location_name or pool.location_id,
            "items_drop_rate": pool.items_drop_rate,
            "requirements": pool.requirements or {},
            "version": pool.version,
            "reward_count": len(pool.rewards_data or []),
        }
        if include_rewards:
            data["rewards"] = self._normalized_rewards(pool)
        return data

    def _serialize_event(self, event):
        return {
            "id": event.id,
            "event_title": event.event_title,
            "is_active": event.is_active,
            "status": event.status,
            "starts_at": _iso(event.starts_at),
            "ends_at": _iso(event.ends_at),
            "activated_at": _iso(event.activated_at),
            "deactivated_at": _iso(event.deactivated_at),
            "modifier_schema_version": event.modifier_schema_version,
            "requires_review": event.requires_review,
            "modifiers": event.modifiers or {},
            "override_loot_pool": event.override_loot_pool,
            "version": event.version,
            "updated_at": event.updated_at.isoformat(),
        }

    def _validate_event_location(self, channel_id, location_id):
        if location_id and not self._find_pool(channel_id, location_id):
            raise ApiProblem(404, "LOCATION_NOT_FOUND", "Override location not found")

    def _serialize_binding(self, binding):
        return {
            "discord_guild_id": binding.discord_guild_id,
            "channel_twitch_id": binding.channel.twitch_id,
            "channel_name": binding.channel.name,
            "management_channel_id": binding.management_channel_id,
            "locale": binding.locale,
        }

    def _check_version(self, current, expected, context):
        if current != expected:
            raise ApiProblem(
                409,
                "CONFIG_VERSION_CONFLICT",
                "Entity was changed by another administrator",
                {"expected_version": expected, "current_version": current},
                context.request_id,
            )

    def _audit(self, context, twitch_id, action, entity_type, entity_id, before, after):
        self.db.add(
            AdminAuditLog(
                request_id=context.request_id,
                idempotency_key=context.idempotency_key,
                channel_twitch_id=(after or before).get("channel_twitch_id", twitch_id),
                actor_twitch_id=twitch_id,
                actor_discord_id=context.discord_user_id,
                actor_service=context.service_name,
                guild_id=context.discord_guild_id,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id),
                before_json=before or {},
                after_json=after or {},
                result="success",
            )
        )
        self.db.flush()

    # --- Fishing cast history -------------------------------------------------

    def list_recent_casts(
        self,
        context,
        channel_twitch_id: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
        user_twitch_id: str | None = None,
        status: str | None = None,
        location_id: str | None = None,
        reward_type: str | None = None,
        start: str | None = None,
        end: str | None = None,
        username: str | None = None,
        event_id: int | None = None,
        item_id: str | None = None,
        has_item: bool | None = None,
        min_mass_delta: float | None = None,
        max_mass_delta: float | None = None,
    ) -> dict:
        channel, _ = self._authorize(context, ChannelPermission.CASTS_READ, channel_twitch_id)
        limit = max(1, min(limit, 100))
        query_repo = FishingCastQueryRepository(self.db)
        user_id = None
        if user_twitch_id:
            user = (
                self.db.query(UserProgress)
                .filter(
                    UserProgress.channel_id == channel.id,
                    UserProgress.user_twitch_id == user_twitch_id,
                )
                .first()
            )
            user_id = user.id if user else -1
        casts, next_cursor = query_repo.recent_casts(
            channel_id=channel.id,
            limit=limit,
            cursor=cursor,
            user_progress_id=user_id,
            status=status,
            location_id=location_id,
            reward_type=reward_type,
            start=_parse_datetime(start),
            end=_parse_datetime(end),
            username=username,
            event_id=event_id,
            item_id=item_id,
            has_item=has_item,
            min_mass_delta=min_mass_delta,
            max_mass_delta=max_mass_delta,
        )
        return {
            "items": [self._serialize_cast_summary(cast) for cast in casts],
            "next_cursor": next_cursor,
        }

    def get_cast_detail(
        self,
        context,
        channel_twitch_id: str,
        cast_id: str,
        *,
        include_technical: bool = False,
    ) -> dict:
        permission = (
            ChannelPermission.CASTS_TECHNICAL_READ
            if include_technical
            else ChannelPermission.CASTS_READ
        )
        channel, _ = self._authorize(context, permission, channel_twitch_id)
        try:
            cast_uuid = uuid.UUID(cast_id)
        except (ValueError, AttributeError, TypeError):
            # Malformed ids must surface as a clean not-found, never as a
            # database DataError / HTTP 500 (fishing_casts.id is a native UUID).
            raise ApiProblem(404, "CAST_NOT_FOUND", "Fishing cast not found")
        query_repo = FishingCastQueryRepository(self.db)
        cast = query_repo.get_cast(str(cast_uuid), channel.id)
        if not cast:
            raise ApiProblem(404, "CAST_NOT_FOUND", "Fishing cast not found")
        return self._serialize_cast_detail(cast, include_technical=include_technical)

    @staticmethod
    def _trace_stage(trace, stage: str) -> dict | None:
        """Return one stage dict from the rng_trace JSONB array."""
        if not isinstance(trace, list):
            return None
        for entry in trace:
            if isinstance(entry, dict) and entry.get("stage") == stage:
                return entry
        return None

    def _cast_reward_detail(self, cast) -> dict:
        """Reward selection detail with read-time fallback to JSONB snapshots.

        Old ledger rows keep the trace in rng_trace and the selected reward in
        reward_snapshot; the dedicated columns were backfilled by migration
        20260806_0024, and this fallback covers any row recorded before it.
        """
        probability = (
            str(cast.reward_probability)
            if cast.reward_probability is not None
            else None
        )
        roll = str(cast.reward_roll) if cast.reward_roll is not None else None
        total_weight = (
            str(cast.reward_total_weight)
            if cast.reward_total_weight is not None
            else None
        )
        weight = (
            str(cast.reward_weight) if cast.reward_weight is not None else None
        )
        reward_id = cast.reward_id
        if probability is None:
            trace = self._trace_stage(cast.rng_trace, "ordinary_reward")
            snapshot = cast.reward_snapshot if isinstance(cast.reward_snapshot, dict) else {}
            if trace:
                probability = trace.get("selected_probability")
                roll = trace.get("roll")
                total_weight = trace.get("total_weight")
            if weight is None and snapshot.get("weight") is not None:
                weight = str(snapshot["weight"])
            if reward_id is None and snapshot.get("reward_id"):
                reward_id = str(snapshot["reward_id"])
        return {
            "reward_id": reward_id,
            "reward_type": cast.reward_type,
            "weight": weight,
            "total_weight": total_weight,
            "probability": probability,
            "roll": roll,
        }

    def _cast_item_drop_detail(self, cast) -> dict:
        probability = (
            str(cast.item_drop_probability)
            if cast.item_drop_probability is not None
            else None
        )
        roll = str(cast.item_drop_roll) if cast.item_drop_roll is not None else None
        if probability is None:
            gate = self._trace_stage(cast.rng_trace, "item_drop_gate")
            if gate:
                probability = gate.get("threshold")
                roll = gate.get("roll")
        return {
            "succeeded": cast.item_drop_succeeded,
            "count": int(cast.item_drop_count or 0),
            "probability": probability,
            "roll": roll,
        }

    def get_cast_summary_stats(
        self,
        context,
        channel_twitch_id: str,
        *,
        start: str | None = None,
        end: str | None = None,
    ) -> dict:
        channel, _ = self._authorize(context, ChannelPermission.CASTS_READ, channel_twitch_id)
        query_repo = FishingCastQueryRepository(self.db)
        start_dt = _parse_datetime(start)
        end_dt = _parse_datetime(end)
        stats = query_repo.summary(
            channel_id=channel.id,
            start=start_dt,
            end=end_dt,
        )
        return {"period": {"start": start, "end": end}, **stats}

    def _serialize_cast_summary(self, cast) -> dict:
        # List/export rows carry the full show-format payload so the Discord
        # list views render every cast exactly like /fish cast show.
        summary = self._serialize_cast_detail(cast, include_technical=False)
        summary["mass_label"] = _format_delta(cast.mass_delta_applied)
        summary["reward_type"] = cast.reward_type
        summary["item_drop_count"] = int(cast.item_drop_count or 0)
        return summary

    def _serialize_cast_detail(self, cast, *, include_technical: bool) -> dict:
        drops = [
            {
                "item_id": drop.item_id_snapshot,
                "title": drop.title_snapshot,
                "quantity_granted": drop.quantity_granted,
                "grant_status": drop.grant_status,
            }
            for drop in cast.item_drops
        ]
        reward = self._cast_reward_detail(cast)
        item_drop = self._cast_item_drop_detail(cast)
        detail = {
            "cast_id": str(cast.id),
            "status": cast.status,
            "error_code": cast.error_code,
            "channel_id": cast.channel_id,
            "user_progress_id": cast.user_progress_id,
            "username": cast.username_snapshot,
            "location_id": cast.location_id,
            "location_name": cast.location_name_snapshot,
            "requested_at": _iso(cast.requested_at),
            "resolved_at": _iso(cast.resolved_at),
            "duration_ms": cast.duration_ms,
            "event": (
                {"id": cast.event_id, "title": cast.event_title_snapshot}
                if cast.event_id
                else None
            ),
            "reward": reward,
            "state": {
                "mass_before": _dec(cast.mass_before),
                "mass_after": _dec(cast.mass_after),
                "mass_delta_applied": _dec(cast.mass_delta_applied),
                "xp_before": cast.xp_before,
                "xp_after": cast.xp_after,
                "xp_gained": cast.xp_gained,
                "level_before": cast.level_before,
                "level_after": cast.level_after,
                "was_level_up": cast.was_level_up,
            },
            "items": drops,
            "item_drop": item_drop,
        }
        if include_technical:
            detail["technical"] = {
                "rng_trace": cast.rng_trace,
                "resolved_modifiers": cast.resolved_modifiers,
                "modifier_sources": cast.modifier_sources,
                "special_result": cast.special_result,
                "result_snapshot": cast.result_snapshot,
                "ruleset_snapshot_id": (
                    str(cast.ruleset_snapshot_id)
                    if cast.ruleset_snapshot_id is not None
                    else None
                ),
            }
        return detail
