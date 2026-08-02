import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from domain.config_schema import EventModifiers, LocationRequirements, RewardDefinition
from domain.item_schema import STAT_REGISTRY, ModifierOperation, ModifierScope, StatKey
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfigChanges(StrictDTO):
    xp_base: int | None = Field(None, ge=0, le=10_000)
    xp_exponent: Decimal | None = Field(None, ge=1, le=5)
    sell_max_bonus: Decimal | None = Field(None, ge=0, le=100)
    sell_mid_level: int | None = Field(None, ge=0, le=1_000_000)
    sell_rate: Decimal | None = Field(None, ge=1, le=100_000)
    buy_rate: Decimal | None = Field(None, ge=1, le=100_000)
    rob_min_chance: Decimal | None = Field(None, ge=0, le=1)
    rob_max_chance: Decimal | None = Field(None, ge=0, le=1)
    rob_resist_divisor: Decimal | None = Field(None, ge=1, le=1_000_000)
    rob_loss_divisor: Decimal | None = Field(None, ge=1, le=1_000_000)
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
    requirements: LocationRequirements | None = None


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


class VersionedDeleteRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)


class DiscordLinkStartResponse(BaseModel):
    authorization_url: str
    expires_in: int


class GuildBindRequest(StrictDTO):
    replace: bool = False


class DiscordEventCreateRequest(StrictDTO):
    event_title: str = Field(..., min_length=1, max_length=120)
    modifiers: EventModifiers = Field(default_factory=EventModifiers)
    override_loot_pool: str | None = Field(
        None,
        pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$",
    )


class DiscordEventPatchRequest(StrictDTO):
    expected_version: int = Field(..., ge=1)
    event_title: str | None = Field(None, min_length=1, max_length=120)
    modifiers: EventModifiers | None = None
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
        if self.operation == ModifierOperation.MULTIPLY:
            if self.value < 0 or self.value > 100:
                raise ValueError("Multiplier must be between 0 and 100")
        elif not definition.minimum <= self.value <= definition.maximum:
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
