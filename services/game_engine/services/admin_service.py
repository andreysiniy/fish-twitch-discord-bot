from datetime import datetime, timedelta, timezone
from typing import Any, List

from core.game_limits import validate_cooldown_seconds, validate_event_duration_seconds
from core.game_params import DEFAULT_GAME_PARAMS, GParam
from core.messages import MsgKey, format_time, resolve_message
from core.security import encrypt_integration_token, integration_key_fingerprint
from core.config import settings
from domain.item_schema import parse_item_definition_payload
from domain.schemas.admin import (
    ALLOWED_CHANNEL_ROLES,
    ChannelAccessResponseDTO,
    ChannelAccessUpsertDTO,
    ChannelCreateDTO,
    ChannelUpdateDTO,
    FishingEventCreateRequestDTO,
    FishingEventListResponseDTO,
    FishingEventResponseDTO,
    FishingEventToggleResponseDTO,
    FishingEventUpdateRequestDTO,
    GrantItemRequestDTO,
    ItemDefinitionCreateDTO,
    PlayerListResponse,
    RewardPoolUpdateDTO,
)
from infrastructure.repositories.channel_repo import ChannelRepository
from infrastructure.repositories.config_repo import ConfigRepository
from infrastructure.repositories.inventory_repo import InventoryRepository
from infrastructure.repositories.user_repo import UserRepository
from infrastructure.models import ChannelEconomySettings, ChannelIntegration
from infrastructure.se_client import SEApiClient
from infrastructure.se_client import ProviderAuthenticationError, ProviderError
from services.eventing.event_lifecycle_service import FishingEventLifecycleService
from services.player_modifier_service import PlayerModifierService
from services.item_dependency_validator import validate_item_dependency_graph


class AdminService:
    def __init__(
        self,
        channel_repo: ChannelRepository,
        user_repo: UserRepository,
        config_repo: ConfigRepository,
        se_client: SEApiClient | None = None,
    ):
        self.repo = channel_repo
        self.user_repo = user_repo
        self.config_repo = config_repo
        self.se_client = se_client or SEApiClient()
        self.event_lifecycle = FishingEventLifecycleService(channel_repo=self.repo)

    def create_channel(self, data: ChannelCreateDTO):
        existing = self.repo.get_by_twitch_id(data.twitch_id)
        if existing:
            raise ValueError(f"Channel {data.name} already exists")
        return self.repo.create(data)

    def get_channels(self, requester_twitch_id: str) -> List:
        channel = self.repo.get_by_twitch_id(requester_twitch_id)
        return [channel] if channel else []

    def check_access(
        self, channel_twitch_id: str, requester_twitch_id: str, owner_only: bool = False
    ):
        channel = self.repo.get_by_twitch_id(channel_twitch_id)
        if not channel:
            raise ValueError("Channel not found")

        is_owner = channel.twitch_id == requester_twitch_id
        if is_owner:
            return channel

        if owner_only:
            raise PermissionError("Only the channel owner can perform this action")

        access = self.repo.get_access_record(channel.id, requester_twitch_id)
        if access and access.role in ALLOWED_CHANNEL_ROLES:
            return channel

        raise PermissionError("Access denied for this channel")

    def get_players(
        self, requester_twitch_id: str, channel_twitch_id: str, skip: int, limit: int
    ) -> PlayerListResponse:
        self.check_access(channel_twitch_id, requester_twitch_id)
        users, total = self.user_repo.get_users_by_channel(channel_twitch_id, skip, limit)
        return PlayerListResponse(total=total, players=users)

    def update_channel_rewards(
        self, requester_twitch_id: str, twitch_id: str, location_id: str, data: RewardPoolUpdateDTO
    ):
        channel = self.check_access(twitch_id, requester_twitch_id)

        return self.repo.update_rewards(
            channel.id,
            location_id,
            [reward.model_dump(mode="json") for reward in data.rewards],
            data.items_drop_rate,
            (
                data.requirements.model_dump(mode="json", exclude_none=True)
                if data.requirements
                else {}
            ),
            data.location_name,
        )

    def get_channel_rewards(self, requester_twitch_id: str, twitch_id: str, location_id: str):
        channel = self.check_access(twitch_id, requester_twitch_id)

        rewards = {}
        loot_pool, item_pool, items_drop_rate = self.config_repo.get_dual_pool(
            twitch_id, location_id
        )
        pool = self.repo.get_rewards(channel.id, location_id)
        requirements = pool.requirements if pool and isinstance(pool.requirements, dict) else {}
        location_name = (
            pool.location_name
            if pool and isinstance(pool.location_name, str) and pool.location_name.strip()
            else location_id
        )

        if not loot_pool:
            rewards = {
                "location_id": location_id,
                "location_name": location_name,
                "requirements": requirements,
                "items_drop_rate": 0,
                "rewards_data": [],
                "items": [],
            }

        rewards.update(
            {
                "location_id": location_id,
                "location_name": location_name,
                "requirements": requirements,
                "items_drop_rate": items_drop_rate,
                "rewards_data": loot_pool,
                "items": item_pool,
            }
        )

        return rewards

    def list_channel_access(
        self, requester_twitch_id: str, channel_twitch_id: str
    ) -> list[ChannelAccessResponseDTO]:
        channel = self.check_access(channel_twitch_id, requester_twitch_id, owner_only=True)
        return [
            ChannelAccessResponseDTO.model_validate(record)
            for record in self.repo.list_access_records(channel.id)
        ]

    def upsert_channel_access(
        self, requester_twitch_id: str, channel_twitch_id: str, data: ChannelAccessUpsertDTO
    ) -> ChannelAccessResponseDTO:
        channel = self.check_access(channel_twitch_id, requester_twitch_id, owner_only=True)

        role = data.role.strip().lower()
        if role not in ALLOWED_CHANNEL_ROLES:
            raise ValueError(
                f"Unsupported role. Allowed values: {', '.join(sorted(ALLOWED_CHANNEL_ROLES))}"
            )
        username = data.user_twitch_name.strip()
        if not username:
            raise ValueError("user_twitch_name is required")

        if data.user_twitch_id == channel.twitch_id:
            raise ValueError("Channel owner role is managed by channel ownership")

        record = self.repo.upsert_access_record(channel.id, data.user_twitch_id, username, role)
        return ChannelAccessResponseDTO.model_validate(record)

    def remove_channel_access(
        self, requester_twitch_id: str, channel_twitch_id: str, user_twitch_id: str
    ) -> None:
        channel = self.check_access(channel_twitch_id, requester_twitch_id, owner_only=True)

        if user_twitch_id == channel.twitch_id:
            raise ValueError("Channel owner role cannot be removed")

        removed = self.repo.delete_access_record(channel.id, user_twitch_id)
        if not removed:
            raise ValueError("Channel access record not found")

    def update_economy_switches(
        self, requester_twitch_id: str, channel_twitch_id: str, action: str
    ) -> dict[str, Any]:
        channel = self.check_access(channel_twitch_id, requester_twitch_id)
        if channel.twitch_id != requester_twitch_id:
            access = self.repo.get_access_record(channel.id, requester_twitch_id)
            if not access or access.role != "editor":
                raise PermissionError("Only the channel owner or an editor can change economy switches")
        row = (
            self.repo.db.query(ChannelEconomySettings)
            .filter(ChannelEconomySettings.channel_id == channel.id)
            .with_for_update()
            .first()
        )
        if row is None:
            row = ChannelEconomySettings(channel_id=channel.id)
            self.repo.db.add(row)
            self.repo.db.flush()
        normalized = action.strip().lower()
        if normalized == "on":
            row.enabled = True
        elif normalized == "off":
            row.enabled = False
        elif normalized == "buy_on":
            row.buy_enabled = True
        elif normalized == "buy_off":
            row.buy_enabled = False
        elif normalized == "sell_on":
            row.sell_enabled = True
        elif normalized == "sell_off":
            row.sell_enabled = False
        elif normalized != "status":
            raise ValueError("Unknown economy switch action")
        if normalized != "status":
            row.version += 1
        self.repo.db.flush()
        return {
            "enabled": row.enabled,
            "buy_enabled": row.buy_enabled,
            "sell_enabled": row.sell_enabled,
            "version": row.version,
        }

    def set_fishing_cooldown(
        self,
        requester_twitch_id: str,
        channel_twitch_id: str,
        seconds: int,
        scope: str | None = None,
    ) -> dict:
        channel = self.check_access(channel_twitch_id, requester_twitch_id)

        normalized_scope = (scope or "").strip().lower()
        if normalized_scope not in {"", "sub"}:
            raise ValueError(
                "Invalid scope. Use empty scope for general cooldown or 'sub' for subscribers"
            )
        seconds = validate_cooldown_seconds(seconds)

        config = dict(channel.config or {})
        custom_params = dict(config.get("custom_params") or {})
        target_key = (
            GParam.SUBS_FISHING_COOLDOWN if normalized_scope == "sub" else GParam.FISHING_COOLDOWN
        )
        custom_params[target_key.value] = seconds
        config["custom_params"] = custom_params
        self.repo.update(channel.id, ChannelUpdateDTO(config=config))

        fishing_cd = int(
            custom_params.get(
                GParam.FISHING_COOLDOWN.value, DEFAULT_GAME_PARAMS[GParam.FISHING_COOLDOWN]
            )
        )
        subs_cd = int(
            custom_params.get(
                GParam.SUBS_FISHING_COOLDOWN.value,
                DEFAULT_GAME_PARAMS[GParam.SUBS_FISHING_COOLDOWN],
            )
        )
        updated_scope = "sub" if normalized_scope == "sub" else "global"
        chat_message = resolve_message(
            config,
            MsgKey.COOLDOWN_UPDATED,
            updated_scope=updated_scope,
            fishing_cooldown=format_time(fishing_cd),
            subs_fishing_cooldown=format_time(subs_cd),
        )

        return {
            "chat_message": chat_message,
            "fishing_cooldown": fishing_cd,
            "subs_fishing_cooldown": subs_cd,
            "updated_scope": updated_scope,
        }

    async def upsert_stream_elements_integration(
        self, requester_twitch_id: str, channel_twitch_id: str, se_token: str
    ) -> dict:
        channel = self.check_access(channel_twitch_id, requester_twitch_id, owner_only=True)
        normalized_token = str(se_token or "").strip()
        if not normalized_token:
            raise ValueError("se_token is required")

        try:
            se_channel_id = await self.se_client.get_channel_id(normalized_token)
        except (PermissionError, ProviderAuthenticationError) as error:
            raise ValueError("Invalid StreamElements token") from error
        except (ValueError, ProviderError) as error:
            raise ValueError("Failed to resolve StreamElements channel") from error

        try:
            ciphertext = encrypt_integration_token(normalized_token)
        except ValueError as error:
            raise ValueError("Integration encryption key is not configured") from error
        integration = (
            self.user_repo.db.query(ChannelIntegration)
            .filter(
                ChannelIntegration.channel_id == channel.id,
                ChannelIntegration.provider == "streamelements",
            )
            .first()
        )
        if integration is None:
            integration = ChannelIntegration(
                channel_id=channel.id,
                provider_channel_id=se_channel_id,
                credential_ciphertext=ciphertext,
                credential_key_version=settings.INTEGRATIONS_ENCRYPTION_KEY_VERSION,
                credential_fingerprint=integration_key_fingerprint(),
                status="connected",
            )
            self.user_repo.db.add(integration)
        else:
            integration.provider_channel_id = se_channel_id
            integration.credential_ciphertext = ciphertext
            integration.credential_key_version = settings.INTEGRATIONS_ENCRYPTION_KEY_VERSION
            integration.credential_fingerprint = integration_key_fingerprint()
            integration.status = "connected"
            integration.version += 1
            integration.last_error_code = None
        self.user_repo.db.flush()

        return {"status": "ok", "se_channel_id": se_channel_id}

    def upsert_item_definition(
        self,
        requester_twitch_id: str,
        data: ItemDefinitionCreateDTO,
        channel_twitch_id: str | None = None,
    ):
        target_channel_twitch_id = (channel_twitch_id or requester_twitch_id).strip()
        channel = self.check_access(target_channel_twitch_id, requester_twitch_id)
        data = parse_item_definition_payload(data.model_dump(mode="python"))

        item_id = data.item_id.strip()
        if not item_id:
            raise ValueError("item_id is required")

        validate_item_dependency_graph(
            self.user_repo.db,
            channel.id,
            item_id,
            data.effects,
        )

        definition = self.repo.upsert_item_definition(
            channel_twitch_id=channel.twitch_id,
            item_id=item_id,
            title=data.title,
            description=data.description,
            item_type=data.item_type.value,
            slot=data.equipment_slot.value if data.equipment_slot else None,
            rarity=data.rarity.value,
            max_durability=data.max_durability,
            max_charges=data.max_charges,
            break_policy=data.break_policy.value,
            stack_size=data.stack_size,
            image_url=data.image_url,
            effects=[effect.model_dump(mode="json") for effect in data.effects],
            schema_version=data.schema_version,
            nominal_value=data.nominal_value,
            expected_version=data.expected_version,
            updated_by=requester_twitch_id,
        )
        return self._serialize_item_definition(definition)

    def list_item_definitions(
        self,
        requester_twitch_id: str,
        skip: int = 0,
        limit: int = 200,
        channel_twitch_id: str | None = None,
    ):
        target_channel_twitch_id = (channel_twitch_id or requester_twitch_id).strip()
        channel = self.check_access(target_channel_twitch_id, requester_twitch_id)
        definitions = self.repo.list_item_definitions(channel.twitch_id, skip=skip, limit=limit)
        return [self._serialize_item_definition(definition) for definition in definitions]

    def grant_item_to_player(self, requester_twitch_id: str, data: GrantItemRequestDTO):
        self.check_access(data.channel_twitch_id, requester_twitch_id)
        user = self.user_repo.get_progress(data.user_twitch_id, data.channel_twitch_id)
        if not user:
            raise ValueError("Player not found")

        slot_bonus = PlayerModifierService(self.user_repo.db).inventory_slot_bonus(user)
        inv_item = InventoryRepository(self.user_repo.db, max_slots_add=slot_bonus).grant_many(
            user,
            [
                {
                    "item_id": data.item_id,
                    "quantity": data.quantity,
                    "slot_id": data.slot_id,
                    "current_durability": data.current_durability,
                    "current_charges": data.current_charges,
                    "meta": data.meta,
                }
            ],
        )[0]
        return inv_item

    def get_player_inventory(
        self, requester_twitch_id: str, channel_twitch_id: str, user_twitch_id: str
    ):
        self.check_access(channel_twitch_id, requester_twitch_id)
        user = self.user_repo.get_progress(user_twitch_id, channel_twitch_id)
        if not user:
            raise ValueError("Player not found")

        items = [
            self._serialize_inventory_item(item)
            for item in self.user_repo.get_user_inventory_items(user.id)
        ]
        equipped_slots = {
            equipped.slot: equipped.inventory_item.slot_id
            for equipped in InventoryRepository(self.user_repo.db).get_equipped(user.id)
        }
        slot_bonus = PlayerModifierService(self.user_repo.db).inventory_slot_bonus(user)
        return {
            "items": items,
            "equipped_slots": equipped_slots,
            "equipped_rod_slot": equipped_slots.get("rod"),
            "max_slots": max(int(getattr(user, "base_inventory_slots", 20) or 20) + slot_bonus, 1),
        }

    def _serialize_inventory_item(self, item):
        definition = item.definition
        logical_item_id = definition.item_id if definition else item.item_id
        title = definition.title if definition else logical_item_id
        if not definition:
            raise ValueError(f"Inventory item {item.id} has no definition")
        return {
            "id": item.id,
            "item_id": logical_item_id,
            "title": title,
            "description": definition.description if definition else None,
            "rarity": definition.rarity if definition else "common",
            "item_type": definition.type,
            "equipment_slot": definition.slot,
            "max_durability": definition.max_durability,
            "max_charges": definition.max_charges,
            "break_policy": definition.break_policy,
            "stack_size": definition.stack_size if definition else 1,
            "image_url": definition.image_url if definition else None,
            "effects": definition.effects or [],
            "definition_version": definition.version,
            "obtained_definition_version": item.obtained_definition_version,
            "quantity": item.quantity,
            "slot_id": item.slot_id,
            "current_durability": item.current_durability,
            "current_charges": item.current_charges,
            "obtained_at": (item.meta or {}).get("obtained_at"),
            "version": item.version,
            "meta": item.meta or {},
        }

    def _serialize_item_definition(self, definition) -> dict:
        channel_twitch_id = ""
        if getattr(definition, "channel", None) is not None:
            channel_twitch_id = str(definition.channel.twitch_id or "")

        return {
            "item_id": definition.item_id,
            "channel_twitch_id": channel_twitch_id,
            "title": definition.title,
            "description": definition.description,
            "item_type": definition.type,
            "equipment_slot": definition.slot,
            "rarity": definition.rarity,
            "max_durability": definition.max_durability,
            "max_charges": definition.max_charges,
            "break_policy": definition.break_policy,
            "stack_size": definition.stack_size,
            "image_url": definition.image_url,
            "effects": list(definition.effects or []),
            "schema_version": definition.schema_version,
            "nominal_value": definition.nominal_value,
            "version": definition.version,
            "is_active": definition.is_active,
            "archived_at": definition.archived_at,
            "updated_at": definition.updated_at,
        }

    def list_fishing_events(
        self, requester_twitch_id: str, channel_twitch_id: str
    ) -> FishingEventListResponseDTO:
        channel = self.check_access(channel_twitch_id, requester_twitch_id)
        channel_config = channel.config or {}
        events = [
            self._serialize_fishing_event(event)
            for event in self.repo.list_fishing_events(channel.id)
        ]
        active_event = next((event for event in events if event.is_active), None)

        if not events:
            return FishingEventListResponseDTO(
                chat_message=resolve_message(channel_config, MsgKey.FISHEVENT_LIST_EMPTY),
                active_event_id=None,
                items=[],
            )

        labels = []
        for event in events:
            status = "CURRENT" if event.is_active else "OPEN"
            labels.append(f"[{event.id}] {event.event_title} [{status}]")

        return FishingEventListResponseDTO(
            chat_message=resolve_message(
                channel_config, MsgKey.FISHEVENT_LIST, events=", ".join(labels)
            ),
            active_event_id=active_event.id if active_event else None,
            items=events,
        )

    def create_fishing_event(
        self, requester_twitch_id: str, channel_twitch_id: str, data: FishingEventCreateRequestDTO
    ) -> FishingEventResponseDTO:
        channel = self.check_access(channel_twitch_id, requester_twitch_id)
        event_title = data.event_title.strip()
        if not event_title:
            raise ValueError("event_title is required")

        event = self.repo.create_fishing_event(
            channel_id=channel.id,
            event_title=event_title,
            modifiers=data.modifiers.model_dump(mode="json"),
            override_loot_pool=data.override_loot_pool,
            is_active=bool(data.is_active),
        )
        if event.is_active:
            self.event_lifecycle.cancel_auto_disable(channel.twitch_id)
        return self._serialize_fishing_event(event)

    def update_fishing_event(
        self,
        requester_twitch_id: str,
        channel_twitch_id: str,
        event_id: int,
        data: FishingEventUpdateRequestDTO,
    ) -> FishingEventResponseDTO:
        channel = self.check_access(channel_twitch_id, requester_twitch_id)
        update_kwargs: dict[str, Any] = {
            "channel_id": channel.id,
            "event_id": event_id,
            "event_title": data.event_title.strip() if data.event_title is not None else None,
            "modifiers": data.modifiers.model_dump(mode="json") if data.modifiers else None,
            "is_active": data.is_active,
        }
        if data.event_title is not None and not update_kwargs["event_title"]:
            raise ValueError("event_title cannot be empty")
        if data.clear_override_loot_pool:
            update_kwargs["override_loot_pool"] = None
        elif data.override_loot_pool is not None:
            update_kwargs["override_loot_pool"] = data.override_loot_pool

        event = self.repo.update_fishing_event(**update_kwargs)
        if not event:
            raise ValueError("Fishing event not found")

        if data.is_active is False:
            self.event_lifecycle.cancel_auto_disable(channel.twitch_id)
        elif data.is_active is True:
            self.event_lifecycle.cancel_auto_disable(channel.twitch_id)
        return self._serialize_fishing_event(event)

    def delete_fishing_event(
        self, requester_twitch_id: str, channel_twitch_id: str, event_id: int
    ) -> None:
        channel = self.check_access(channel_twitch_id, requester_twitch_id)
        event = self.repo.get_fishing_event(channel.id, event_id)
        if not event:
            raise ValueError("Fishing event not found")

        was_active = bool(event.is_active)
        removed = self.repo.delete_fishing_event(channel.id, event_id)
        if not removed:
            raise ValueError("Fishing event not found")
        if was_active:
            self.event_lifecycle.cancel_auto_disable(channel.twitch_id)

    def toggle_fishing_event(
        self,
        requester_twitch_id: str,
        channel_twitch_id: str,
        event_id: int,
        duration_seconds: int | None = None,
    ) -> FishingEventToggleResponseDTO:
        channel = self.check_access(channel_twitch_id, requester_twitch_id)
        target = self.repo.get_fishing_event(channel.id, event_id)
        if not target:
            raise ValueError("Fishing event not found")

        active = self.repo.get_active_fishing_event(channel.id)
        self.event_lifecycle.cancel_auto_disable(channel.twitch_id)

        if active and active.id == target.id:
            self.repo.set_active_fishing_event(channel.id, None)
            refreshed = self.repo.get_fishing_event(channel.id, target.id)
            return FishingEventToggleResponseDTO(
                status="deactivated",
                chat_message=resolve_message(
                    channel.config or {},
                    MsgKey.FISHEVENT_DISABLED,
                    event_id=refreshed.id if refreshed else target.id,
                    event_title=refreshed.event_title if refreshed else target.event_title,
                ),
                event=self._serialize_fishing_event(refreshed) if refreshed else None,
                active_event_id=None,
            )

        activated = self.repo.set_active_fishing_event(channel.id, target.id)
        if not activated:
            raise ValueError("Fishing event not found")

        now = datetime.now(timezone.utc)
        scheduled_disable_at = None
        scheduler_job = None
        if duration_seconds is not None:
            duration_seconds = validate_event_duration_seconds(duration_seconds)
            # Durable deadline in PostgreSQL: the reconciler ends the event at
            # this time even if the Redis job is lost (plan §15).
            activated.ends_at = now + timedelta(seconds=duration_seconds)
            scheduler_job = self.event_lifecycle.schedule_auto_disable(
                channel_twitch_id=channel.twitch_id,
                channel_id=channel.id,
                event_id=activated.id,
                event_title=activated.event_title,
                delay_seconds=duration_seconds,
                requested_by=requester_twitch_id,
            )
            scheduled_disable_at = int(scheduler_job.get("execute_at", 0) or 0)
        else:
            # Indefinite activation: clear the stale deactivation timestamp so
            # the durable reconciler does not end the event immediately.
            activated.ends_at = None
        self.repo.db.flush()

        return FishingEventToggleResponseDTO(
            status="activated",
            chat_message=resolve_message(
                channel.config or {},
                MsgKey.FISHEVENT_ENABLED_TIMED
                if duration_seconds is not None
                else MsgKey.FISHEVENT_ENABLED,
                event_id=activated.id,
                event_title=activated.event_title,
                duration=format_time(duration_seconds) if duration_seconds is not None else "",
            ),
            event=self._serialize_fishing_event(activated),
            active_event_id=activated.id,
            scheduled_disable_at=scheduled_disable_at,
            scheduler_job=scheduler_job,
        )

    def _serialize_fishing_event(self, event) -> FishingEventResponseDTO:
        return FishingEventResponseDTO(
            id=event.id,
            event_title=event.event_title,
            is_active=bool(event.is_active),
            modifiers=dict(event.modifiers or {}),
            override_loot_pool=event.override_loot_pool,
        )
