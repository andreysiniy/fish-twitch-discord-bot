import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GameConfig(StrictModel):
    xp_base: int = Field(100, ge=0, le=10_000)
    xp_exponent: Decimal = Field(Decimal("1.5"), ge=1, le=5)
    sell_max_bonus: Decimal = Field(Decimal("2.0"), ge=0, le=100)
    sell_mid_level: int = Field(50, ge=0, le=1_000_000)
    sell_rate: Decimal = Field(Decimal(100), ge=1, le=100_000)
    buy_rate: Decimal = Field(Decimal(120), ge=1, le=100_000)
    rob_min_chance: Decimal = Field(Decimal("0.05"), ge=0, le=1)
    rob_max_chance: Decimal = Field(Decimal("0.95"), ge=0, le=1)
    rob_resist_divisor: Decimal = Field(Decimal(100), ge=1, le=1_000_000)
    rob_loss_divisor: Decimal = Field(Decimal(50), ge=1, le=1_000_000)
    rob_base_chance: Decimal = Field(Decimal("0.8"), ge=0, le=1)
    fishing_cooldown: int = Field(600, ge=0, le=86_400)
    subs_fishing_cooldown: int = Field(300, ge=0, le=86_400)

    @model_validator(mode="after")
    def validate_chance_range(self):
        if self.rob_min_chance > self.rob_max_chance:
            raise ValueError("rob_min_chance must not exceed rob_max_chance")
        return self


class LocationRequirements(StrictModel):
    level: int | None = Field(None, ge=0, le=1_000_000)
    total_fish_stat: int | None = Field(None, ge=0, le=1_000_000_000)
    total_mass_stat: Decimal | None = Field(None, ge=0, le=1_000_000_000)


class RewardBase(StrictModel):
    reward_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    weight: int = Field(1, ge=1, le=1_000_000)
    name: str | None = Field(None, min_length=1, max_length=80)
    xp: int = Field(0, ge=0, le=1_000_000)
    message: str = Field("", max_length=300)


class FishReward(RewardBase):
    type: Literal["fish"]
    min_mass: Decimal | None = Field(None, ge=-1_000_000, le=1_000_000)
    max_mass: Decimal | None = Field(None, ge=-1_000_000, le=1_000_000)
    fixed_mass: Decimal | None = Field(None, ge=-1_000_000, le=1_000_000)
    percentage: Decimal | None = Field(None, ge=-1, le=1)

    @model_validator(mode="after")
    def validate_mass_mode(self):
        has_range = self.min_mass is not None or self.max_mass is not None
        modes = sum([has_range, self.fixed_mass is not None, self.percentage is not None])
        if modes != 1:
            raise ValueError("fish reward must use exactly one mass mode")
        if has_range:
            if self.min_mass is None or self.max_mass is None:
                raise ValueError("both min_mass and max_mass are required")
            if self.min_mass > self.max_mass:
                raise ValueError("min_mass must not exceed max_mass")
        return self


class TimeoutReward(RewardBase):
    type: Literal["timeout"]
    duration: int = Field(..., ge=1, le=1_209_600)
    reason: str = Field("", max_length=200)


class PointsReward(RewardBase):
    type: Literal["points"]
    value: int = Field(..., ge=-1_000_000, le=1_000_000)


class RobberyReward(RewardBase):
    type: Literal["robbery"]
    percentage: Decimal | None = Field(None, ge=0, le=1)
    mass: Decimal | None = Field(None, ge=0, le=1_000_000)
    range: int = Field(3, ge=1, le=100)
    success_message: str = Field("", max_length=300)

    @model_validator(mode="after")
    def validate_robbery_mode(self):
        if (self.percentage is None) == (self.mass is None):
            raise ValueError("robbery reward requires exactly one of percentage or mass")
        return self


class AddMassOutcome(StrictModel):
    type: Literal["add_mass"]
    mass: Decimal = Field(..., ge=-1_000_000, le=1_000_000)


class AddPercentageMassOutcome(StrictModel):
    type: Literal["add_percentage_mass"]
    percentage: Decimal = Field(..., ge=-1, le=1)


class TimeoutOutcome(StrictModel):
    type: Literal["timeout"]
    duration: int = Field(..., ge=1, le=1_209_600)
    reason: str = Field("", max_length=200)


RouletteOutcome = Annotated[
    AddMassOutcome | AddPercentageMassOutcome | TimeoutOutcome,
    Field(discriminator="type"),
]


class RussianRouletteReward(RewardBase):
    type: Literal["russian_roulette"]
    bullets: int = Field(1, ge=1, le=6)
    chambers: int = Field(6, ge=1, le=100)
    safe_message: str = Field("", max_length=300)
    shot_message: str = Field("", max_length=300)
    reward: RouletteOutcome | None = None
    penalty: RouletteOutcome | None = None

    @model_validator(mode="after")
    def validate_chambers(self):
        if self.bullets > self.chambers:
            raise ValueError("bullets must not exceed chambers")
        return self


class NothingReward(RewardBase):
    type: Literal["nothing"]


class DupeReward(RewardBase):
    type: Literal["dupe"]
    amount: int = Field(..., ge=1, le=20)
    delay: int = Field(0, ge=0, le=60)


RewardDefinition = Annotated[
    FishReward
    | TimeoutReward
    | PointsReward
    | RobberyReward
    | RussianRouletteReward
    | DupeReward
    | NothingReward,
    Field(discriminator="type"),
]


class EventModifiers(StrictModel):
    """Legacy v1 modifier schema. Kept for migration/back-compat only."""

    luck_mult: Decimal = Field(Decimal(1), ge=0, le=100)
    xp_mult: Decimal = Field(Decimal(1), ge=0, le=100)
    cd_reduction: Decimal = Field(Decimal(0), ge=0, le=Decimal("0.95"))
    bonus_mass: Decimal = Field(
        Decimal(0),
        ge=0,
        le=100,
        description="Relative mass bonus where 0.15 adds 15 percent",
    )


class EventModifiersV2(StrictModel):
    """Public v2 event modifier schema using ordinary human percentages.

    ``5`` means exactly ``5%``, ``-50`` means a ``50%`` reduction, and ``0`` is
    neutral. Fish luck only affects fish-reward magnitude; item drop uses its own
    stats.
    """

    schema_version: int = Field(2, ge=2, le=2)
    fish_luck_change_percent: Decimal = Field(Decimal(0), ge=-500, le=2000)
    positive_fish_reward_change_percent: Decimal = Field(Decimal(0), ge=-500, le=2000)
    negative_fish_reward_change_percent: Decimal = Field(Decimal(0), ge=-100, le=2000)
    xp_gain_change_percent: Decimal = Field(Decimal(0), ge=-500, le=2000)
    cooldown_change_percent: Decimal = Field(Decimal(0), ge=-100, le=95)
    item_drop_chance_add_pp: Decimal = Field(Decimal(0), ge=-100, le=100)
    item_rarity_luck_change_percent: Decimal = Field(Decimal(0), ge=-500, le=2000)
    robbery_protection_percent: Decimal = Field(Decimal(0), ge=0, le=100)
    robbery_evasion_percent: Decimal = Field(Decimal(0), ge=0, le=100)

    def to_resolver_payload(self) -> dict[str, Decimal]:
        """Map v2 human percentages to resolver stat ratios (ratios, not percent)."""

        def pct(value: Decimal) -> Decimal:
            return value / Decimal("100")

        return {
            "loot_luck_pct": pct(self.fish_luck_change_percent),
            "positive_mass_bonus_pct": pct(self.positive_fish_reward_change_percent),
            "negative_mass_reduction_pct": pct(self.negative_fish_reward_change_percent),
            "xp_gain_bonus_pct": pct(self.xp_gain_change_percent),
            "cooldown_reduction_pct": pct(self.cooldown_change_percent),
            "item_drop_chance_add": pct(self.item_drop_chance_add_pp),
            "item_rarity_luck_pct": pct(self.item_rarity_luck_change_percent),
            "robbery_protection_pct": pct(self.robbery_protection_percent),
            "robbery_evasion_pct": pct(self.robbery_evasion_percent),
        }
