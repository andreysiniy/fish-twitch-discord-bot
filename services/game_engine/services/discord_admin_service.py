import json
import secrets
import uuid
from datetime import datetime, timezone
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
    Channel,
    DiscordAccountLink,
    DiscordGuildBinding,
    FishingEvent,
    InventoryItem,
    ItemDefinition,
    LocationItem,
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
        self, context, channel_twitch_id: str, user_twitch_id: str
    ) -> dict[str, Any]:
        channel, _ = self._authorize(
            context, ChannelPermission.PLAYER_MODIFIERS_READ, channel_twitch_id
        )
        user = self._find_player(channel.id, user_twitch_id)
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
        user_twitch_id: str,
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
            user = self._find_player(channel.id, user_twitch_id, for_update=True)
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
        user_twitch_id: str,
        modifier_id: str,
        data: VersionedStateRequest,
    ) -> dict[str, Any]:
        def mutation() -> dict[str, Any]:
            channel, link = self._authorize(
                context, ChannelPermission.PLAYER_MODIFIERS_WRITE, channel_twitch_id
            )
            user = self._find_player(channel.id, user_twitch_id)
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
        user_twitch_id: str,
        modifier_id: str,
        expected_version: int,
    ) -> dict[str, Any]:
        def mutation() -> dict[str, Any]:
            channel, link = self._authorize(
                context, ChannelPermission.PLAYER_MODIFIERS_WRITE, channel_twitch_id
            )
            user = self._find_player(channel.id, user_twitch_id)
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
        user_twitch_id: str,
        scope: ModifierScope,
    ) -> dict[str, Any]:
        channel, _ = self._authorize(
            context, ChannelPermission.PLAYER_MODIFIERS_READ, channel_twitch_id
        )
        user = self._find_player(channel.id, user_twitch_id)
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

        return self.idempotency.execute(
            context.actor_scope,
            context.idempotency_key,
            "item.upsert",
            data.model_dump(mode="json"),
            context.request_id,
            mutation,
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

    def list_item_drops(
        self, context, channel_twitch_id: str, location_id: str
    ) -> dict:
        pool, _, _ = self._resolve_pool(
            context, channel_twitch_id, location_id, ChannelPermission.ITEMS_READ
        )
        rows = (
            self.db.query(LocationItem)
            .filter(LocationItem.reward_pool_id == pool.id)
            .order_by(LocationItem.id.asc())
            .all()
        )
        return {
            "location_id": pool.location_id,
            "items": [self._serialize_item_drop(row) for row in rows],
        }

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
            row = (
                self.db.query(LocationItem)
                .filter(
                    LocationItem.reward_pool_id == pool.id,
                    LocationItem.item_id == definition.id,
                )
                .with_for_update(of=LocationItem)
                .first()
            )
            before = self._serialize_item_drop(row) if row else {}
            if row:
                if data.expected_version is None:
                    raise ApiProblem(
                        409,
                        "CONFIG_VERSION_CONFLICT",
                        "expected_version is required when editing an item drop",
                    )
                self._check_version(row.version, data.expected_version, context)
                row.version += 1
            else:
                if data.expected_version is not None:
                    raise ApiProblem(409, "CONFIG_VERSION_CONFLICT", "Item drop does not exist")
                row = LocationItem(reward_pool_id=pool.id, item_id=definition.id)
                self.db.add(row)
            row.weight = data.weight
            row.xp_gain = data.xp_gain
            row.quantity = data.quantity
            row.message = data.message
            self.db.flush()
            after = self._serialize_item_drop(row)
            self._audit(
                context,
                link.twitch_user_id,
                "item_drop.upsert",
                "location_item",
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
            row = (
                self.db.query(LocationItem)
                .filter(
                    LocationItem.reward_pool_id == pool.id,
                    LocationItem.item_id == definition.id,
                )
                .with_for_update(of=LocationItem)
                .first()
            )
            if not row:
                raise ApiProblem(404, "ITEM_DROP_NOT_FOUND", "Item drop not found")
            self._check_version(row.version, expected_version, context)
            before = self._serialize_item_drop(row)
            self.db.delete(row)
            self.db.flush()
            self._audit(
                context,
                link.twitch_user_id,
                "item_drop.remove",
                "location_item",
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
        self, context, channel_twitch_id: str, user_twitch_id: str
    ) -> dict:
        channel, _ = self._authorize(
            context, ChannelPermission.PLAYER_INVENTORY_READ, channel_twitch_id
        )
        user = self._find_player(channel.id, user_twitch_id)
        response = InventoryService(UserRepository(self.db)).get_inventory_msg(
            user.user_twitch_id, channel.twitch_id
        )
        return response.model_dump(mode="json")

    def grant_player_item(
        self,
        context,
        channel_twitch_id: str,
        user_twitch_id: str,
        data: PlayerItemGrantRequest,
    ) -> dict:
        def mutation() -> dict:
            channel, link = self._authorize(
                context, ChannelPermission.PLAYER_ITEMS_GRANT, channel_twitch_id
            )
            user = self._find_player(channel.id, user_twitch_id)
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
        user_twitch_id: str,
        inventory_item_id: int,
        data: PlayerItemRevokeRequest,
    ) -> dict:
        def mutation() -> dict:
            channel, link = self._authorize(
                context, ChannelPermission.PLAYER_ITEMS_GRANT, channel_twitch_id
            )
            user = self._find_player(channel.id, user_twitch_id)
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
            self._check_version(event.version, data.expected_version, context)
            before = self._serialize_event(event)
            for candidate in events:
                candidate.is_active = candidate.id == event.id
                if candidate.id == event.id:
                    candidate.version += 1
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
    def _serialize_item_drop(row: LocationItem) -> dict:
        return {
            "id": row.id,
            "item_id": row.definition.item_id,
            "title": row.definition.title,
            "weight": row.weight,
            "xp_gain": row.xp_gain,
            "quantity": row.quantity,
            "message": row.message,
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
        query_repo = FishingCastQueryRepository(self.db)
        cast = query_repo.get_cast(cast_id, channel.id)
        if not cast:
            raise ApiProblem(404, "CAST_NOT_FOUND", "Fishing cast not found")
        return self._serialize_cast_detail(cast, include_technical=include_technical)

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
        reward_type = cast.reward_type
        mass_label = _format_delta(cast.mass_delta_applied)
        xp = int(cast.xp_gained or 0)
        return {
            "cast_id": cast.id,
            "requested_at": _iso(cast.requested_at),
            "status": cast.status,
            "username": cast.username_snapshot,
            "location_id": cast.location_id,
            "reward_type": reward_type,
            "mass_delta_applied": str(cast.mass_delta_applied) if cast.mass_delta_applied is not None else None,
            "xp_gained": xp,
            "mass_label": mass_label,
            "item_drop_count": int(cast.item_drop_count or 0),
            "event_title": cast.event_title_snapshot,
        }

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
        detail = {
            "cast_id": cast.id,
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
            "reward": {
                "reward_id": cast.reward_id,
                "reward_type": cast.reward_type,
                "probability": (
                    str(cast.reward_probability) if cast.reward_probability is not None else None
                ),
                "roll": str(cast.reward_roll) if cast.reward_roll is not None else None,
            },
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
            "item_drop": {
                "succeeded": cast.item_drop_succeeded,
                "count": int(cast.item_drop_count or 0),
                "probability": (
                    str(cast.item_drop_probability) if cast.item_drop_probability is not None else None
                ),
            },
        }
        if include_technical:
            detail["technical"] = {
                "rng_trace": cast.rng_trace,
                "resolved_modifiers": cast.resolved_modifiers,
                "modifier_sources": cast.modifier_sources,
                "special_result": cast.special_result,
                "result_snapshot": cast.result_snapshot,
                "ruleset_snapshot_id": cast.ruleset_snapshot_id,
            }
        return detail
