import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from domain.config_schema import (
    EventModifiers,
    EventModifiersV2,
    LocationRequirements,
    RewardDefinition,
)
from domain.item_schema import (
    STAT_REGISTRY,
    ItemDefinitionData,
    ModifierOperation,
    ModifierScope,
    StatKey,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_TRANSACTION_MASS = Decimal(2147483647)


class StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfigChanges(StrictDTO):
    xp_base: int | None = Field(None, ge=0, le=10_000)
    xp_exponent: Decimal | None = Field(None, ge=1, le=5)
    rob_min_chance: Decimal | None = Field(None, ge=0, le=1)
    rob_max_chance: Decimal | None = Field(None, ge=0, le=1)
    rob_base_chance: Decimal | None = Field(None, ge=0, le=1)
    fishing_cooldown: int | None = Field(None, ge=0, le=86_400)
    subs_fishing_cooldown: int | None = Field(None, ge=0, le=86_400)


class ConfigPatchRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    changes: ConfigChanges


class ConfigResetRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    section: str


class MessageTemplatePatchRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    template: str | None = Field(None, max_length=500)


class LocationCreateRequest(StrictDTO):
    location_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")
    location_name: str = Field(..., min_length=1, max_length=80)
    items_drop_rate: Decimal = Field(Decimal("0.1"), ge=0, le=1)
    requirements: LocationRequirements = Field(default_factory=LocationRequirements)


class LocationPatchRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    location_name: str | None = Field(None, min_length=1, max_length=80)
    items_drop_rate: Decimal | None = Field(None, ge=0, le=1)
    requirements: dict[str, Any] | LocationRequirements | None = None


class RewardCreateRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    reward: RewardDefinition


class RewardPatchRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    reward: RewardDefinition


class LegacyRewardImportRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    payload: dict[str, Any]
    replace_existing: bool = False
    dry_run: bool = False

    @model_validator(mode="after")
    def validate_payload_size(self):
        if len(json.dumps(self.payload, ensure_ascii=False).encode("utf-8")) > 1_048_576:
            raise ValueError("Legacy reward JSON must not exceed 1 MiB")
        return self


class GuildBindRequest(StrictDTO):
    replace: bool = False


class ReconciliationActionRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=1, max_length=500)


def _coerce_event_modifiers(
    value: Any,
) -> EventModifiersV2 | None:
    """Accept only the v2 (human-percent) modifier schema.

    Legacy v1 payloads (``luck_mult``/``xp_mult``/``cd_reduction``/``bonus_mass``)
    are rejected with an explicit error: the Discord UI contract is v2-only and
    legacy events were migrated in 0011. ``None`` is passed through untouched so
    partial patches do not reset to defaults.
    """
    if value is None:
        return None
    if isinstance(value, EventModifiersV2):
        return value
    if isinstance(value, EventModifiers):
        raise ValueError(
            "Legacy v1 event modifiers are no longer accepted; "
            "use human-percent v2 fields (fish_luck_change_percent, etc.)"
        )
    data = dict(value or {})
    if data.get("schema_version") == 2:
        return EventModifiersV2(**data)
    raise ValueError(
        "Event modifiers must be the v2 human-percent schema "
        "(set schema_version=2 and use the *_change_percent fields)"
    )


class DiscordEventCreateRequest(StrictDTO):
    event_title: str = Field(..., min_length=1, max_length=120)
    modifiers: Any = Field(default_factory=EventModifiersV2.model_construct)

    @field_validator("modifiers", mode="before")
    @classmethod
    def validate_modifiers(cls, value: Any) -> Any:
        return _coerce_event_modifiers(value)

    override_loot_pool: str | None = Field(
        None,
        pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$",
    )


class DiscordEventPatchRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    event_title: str | None = Field(None, min_length=1, max_length=120)
    modifiers: Any | None = None

    @field_validator("modifiers", mode="before")
    @classmethod
    def validate_modifiers(cls, value: Any) -> Any:
        if value is None or isinstance(value, EventModifiersV2):
            return value
        if isinstance(value, EventModifiers):
            raise ValueError(
                "Legacy v1 event modifiers are no longer accepted; use human-percent v2 fields"
            )
        data = dict(value or {})
        if data.get("schema_version") != 2:
            raise ValueError("Event modifier patches must set schema_version=2")
        # Keep omitted fields omitted so the service can merge the patch with
        # the stored v2 document instead of resetting hidden values to zero.
        return data

    override_loot_pool: str | None = Field(
        None,
        pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$",
    )


class DiscordEventStartRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    duration_seconds: int | None = Field(None, ge=1, le=1_209_600)


class PlayerModifierSetRequest(StrictDTO):
    stat_key: StatKey
    operation: ModifierOperation = ModifierOperation.ADD
    value: Decimal
    scope: ModifierScope
    source_key: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_.:-]{0,119}$")
    reason: str = Field(..., min_length=1, max_length=300)
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    expected_version: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def validate_modifier(self):
        definition = STAT_REGISTRY[self.stat_key]
        if self.scope != ModifierScope.ALL and self.scope not in definition.scopes:
            raise ValueError(f"{self.stat_key.value} is not available in {self.scope.value}")
        if self.operation not in definition.allowed_operations:
            raise ValueError(f"{self.operation.value} is not allowed for {self.stat_key.value}")
        if self.operation == ModifierOperation.MULTIPLY:
            if self.value < 0 or self.value > 100:
                raise ValueError("Multiplier must be between 0 and 100")
        else:
            if (
                definition.value_type == "integer"
                and self.value != self.value.to_integral_value()
            ):
                raise ValueError(f"{self.stat_key.value} must be an integer")
            if not definition.minimum <= self.value <= definition.maximum:
                raise ValueError(
                    f"{self.stat_key.value} must be between "
                    f"{definition.minimum} and {definition.maximum}"
                )
        if self.starts_at and self.expires_at and self.expires_at <= self.starts_at:
            raise ValueError("expires_at must be later than starts_at")
        return self


class VersionedStateRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    is_enabled: bool


class DiscordItemUpsertRequest(ItemDefinitionData):
    expected_version: int | None = Field(None, ge=1)


class ItemDropUpsertRequest(StrictDTO):
    item_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,119}$")
    weight: int = Field(100, ge=1, le=1_000_000)
    xp_gain: int = Field(0, ge=0, le=1_000_000)
    quantity: int | None = Field(None, ge=0, le=1_000_000_000)
    min_quantity: int = Field(1, ge=1, le=1_000_000_000)
    max_quantity: int = Field(1, ge=1, le=1_000_000_000)
    message: str = Field("You caught {name}!", max_length=300)
    expected_version: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def validate_quantity_range(self):
        if self.max_quantity < self.min_quantity:
            raise ValueError("max_quantity must not be below min_quantity")
        return self


class PlayerItemGrantRequest(StrictDTO):
    item_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,119}$")
    quantity: int = Field(1, ge=1, le=1_000_000)
    slot_id: int | None = Field(None, ge=1)
    current_durability: int | None = Field(None, ge=0)
    current_charges: int | None = Field(None, ge=0)
    meta: dict[str, Any] = Field(default_factory=dict)


class PlayerItemRevokeRequest(StrictDTO):
    quantity: int = Field(1, ge=1, le=1_000_000)
    expected_version: int = Field(..., ge=1)


class PlayerOverflowItemDTO(StrictDTO):
    id: int = Field(..., ge=1)
    version: int = Field(..., ge=1)


class PlayerOverflowClaimRequest(StrictDTO):
    items: list[PlayerOverflowItemDTO] = Field(..., min_length=1, max_length=200)


class StreamElementsConnectRequest(StrictDTO):
    jwt_token: str = Field(..., min_length=20, max_length=4096)


class EconomySettingsPatchRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    buy_points_per_kg: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=4)
    sell_points_per_kg: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=4)
    buy_enabled: bool | None = None
    sell_enabled: bool | None = None
    enabled: bool | None = None
    min_transaction_mass: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    max_transaction_mass: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)

    @field_validator("max_transaction_mass", mode="before")
    @classmethod
    def normalize_max_transaction_mass(cls, value):
        if isinstance(value, str) and value.strip().upper() == "MAX_NUMBER":
            return MAX_TRANSACTION_MASS
        return value

    @model_validator(mode="after")
    def validate_rate_pair(self):
        if (self.buy_points_per_kg is None) != (self.sell_points_per_kg is None):
            raise ValueError("buy_points_per_kg and sell_points_per_kg must be provided together")
        if (
            self.min_transaction_mass is not None
            and self.max_transaction_mass is not None
            and self.max_transaction_mass < self.min_transaction_mass
        ):
            raise ValueError("max_transaction_mass must not be below min_transaction_mass")
        return self
