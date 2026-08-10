from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictItemModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ItemType(str, Enum):
    EQUIPMENT = "equipment"
    CONSUMABLE = "consumable"
    LOOTBOX = "lootbox"
    MATERIAL = "material"
    QUEST = "quest"
    CURRENCY = "currency"
    COLLECTIBLE = "collectible"


class EquipmentSlot(str, Enum):
    ROD = "rod"
    BAIT = "bait"
    DEFENSE = "defense"
    STORAGE = "storage"
    CHARM_1 = "charm_1"
    CHARM_2 = "charm_2"


class ItemRarity(str, Enum):
    COMMON = "common"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"


class BreakPolicy(str, Enum):
    INDESTRUCTIBLE = "indestructible"
    RETAIN_BROKEN = "retain_broken"
    UNEQUIP_BROKEN = "unequip_broken"
    DESTROY_AT_ZERO = "destroy_at_zero"


class ModifierOperation(str, Enum):
    ADD = "add"
    MULTIPLY = "multiply"
    OVERRIDE = "override"
    MIN = "min"
    MAX = "max"


class ModifierScope(str, Enum):
    FISHING = "fishing"
    ROBBERY = "robbery"
    ECONOMY = "economy"
    INVENTORY = "inventory"
    ALL = "all"


class StatKey(str, Enum):
    # v2 modifier schema: ratios, where 0.40 means +40%.
    FISH_LUCK_CHANGE_RATIO = "fish_luck_change_ratio"
    POSITIVE_FISH_REWARD_CHANGE_RATIO = "positive_fish_reward_change_ratio"
    NEGATIVE_FISH_REWARD_CHANGE_RATIO = "negative_fish_reward_change_ratio"
    XP_GAIN_CHANGE_RATIO = "xp_gain_change_ratio"
    COOLDOWN_CHANGE_RATIO = "cooldown_change_ratio"
    POINTS_FLAT_BONUS = "points_flat_bonus"
    ITEM_DROP_CHANCE_ADD = "item_drop_chance_add"
    ITEM_RARITY_LUCK_PCT = "item_rarity_luck_pct"
    EMPTY_CATCH_REROLL_CHANCE_PCT = "empty_catch_reroll_chance_pct"
    ROBBERY_PROTECTION_PCT = "robbery_protection_pct"
    ROBBERY_EVASION_PCT = "robbery_evasion_pct"
    PROTECTED_MASS_FLAT = "protected_mass_flat"
    ROBBERY_COUNTER_CHANCE_PCT = "robbery_counter_chance_pct"
    ROBBERY_ATTACK_CHANCE_ADD = "robbery_attack_chance_add"
    ROBBERY_AMOUNT_BONUS_PCT = "robbery_amount_bonus_pct"
    INVENTORY_SLOTS_ADD = "inventory_slots_add"
    SELL_RATE_BONUS_PCT = "sell_rate_bonus_pct"
    BUY_DISCOUNT_PCT = "buy_discount_pct"


class StatDefinition(StrictItemModel):
    value_type: Literal["decimal", "integer"] = "decimal"
    minimum: Decimal
    maximum: Decimal
    default_operation: ModifierOperation
    scopes: frozenset[ModifierScope]
    allowed_sources: frozenset[str]
    description: str


PERCENT_MIN = Decimal("-0.95")
PERCENT_MAX = Decimal("10")
CHANCE_MIN = Decimal("0")
CHANCE_MAX = Decimal("1")
ALL_SOURCES = frozenset({"item", "event", "channel", "temporary", "player_modifier"})

# Legacy stat keys renamed by modifiers v2 (spec section 17.1). The migration
# rewrites stored data; this mapping additionally translates legacy payloads at
# read time so old item effects and player modifier rows keep resolving during
# the transition period. ``negative_mass_reduction_pct`` and
# ``cooldown_reduction_pct`` flip sign: a 0.20 reduction becomes -0.20 change.
LEGACY_STAT_KEY_MIGRATION: dict[str, str] = {
    "loot_luck_pct": "fish_luck_change_ratio",
    "positive_mass_bonus_pct": "positive_fish_reward_change_ratio",
    "negative_mass_reduction_pct": "negative_fish_reward_change_ratio",
    "xp_gain_bonus_pct": "xp_gain_change_ratio",
    "cooldown_reduction_pct": "cooldown_change_ratio",
}
_SIGN_FLIP_KEYS = frozenset({"negative_mass_reduction_pct", "cooldown_reduction_pct"})


def migrate_stat_key(key: str, value: Decimal) -> tuple[StatKey, Decimal]:
    """Translate a (possibly legacy) stat key into the v2 StatKey with the
    correct sign convention. Raises ``ValueError`` for unknown keys so that
    data written under an unrecognized schema never resolves silently."""
    legacy = str(key or "")
    new_key = LEGACY_STAT_KEY_MIGRATION.get(legacy, legacy)
    if new_key not in {member.value for member in StatKey}:
        raise ValueError(f"Unknown stat key: {legacy}")
    member = StatKey(new_key)
    if legacy in _SIGN_FLIP_KEYS:
        return member, -value
    return member, value


def _stat(
    minimum: str,
    maximum: str,
    scopes: set[ModifierScope],
    description: str,
    operation: ModifierOperation = ModifierOperation.ADD,
    value_type: Literal["decimal", "integer"] = "decimal",
) -> StatDefinition:
    return StatDefinition(
        value_type=value_type,
        minimum=Decimal(minimum),
        maximum=Decimal(maximum),
        default_operation=operation,
        scopes=frozenset(scopes),
        allowed_sources=ALL_SOURCES,
        description=description,
    )


STAT_REGISTRY: dict[StatKey, StatDefinition] = {
    StatKey.FISH_LUCK_CHANGE_RATIO: _stat(
        "-0.50", "1.00", {ModifierScope.FISHING},
        "Fish luck ratio; affects only the magnitude of fish rewards.",
    ),
    StatKey.POSITIVE_FISH_REWARD_CHANGE_RATIO: _stat(
        "-0.50", "2.00", {ModifierScope.FISHING},
        "Change ratio applied only to positive fish rewards.",
    ),
    StatKey.NEGATIVE_FISH_REWARD_CHANGE_RATIO: _stat(
        "-1.00", "1.00", {ModifierScope.FISHING},
        "Change ratio applied only to negative fish rewards "
        "(negative softens the penalty).",
    ),
    StatKey.XP_GAIN_CHANGE_RATIO: _stat(
        "-1.00", "4.00", {ModifierScope.FISHING}, "Fishing XP gain change ratio."
    ),
    StatKey.POINTS_FLAT_BONUS: _stat(
        "-1000000",
        "1000000",
        {ModifierScope.FISHING},
        "Flat points reward adjustment.",
        value_type="integer",
    ),
    StatKey.ITEM_DROP_CHANCE_ADD: _stat(
        "-1", "1", {ModifierScope.FISHING}, "Additive item-drop probability."
    ),
    StatKey.ITEM_RARITY_LUCK_PCT: _stat(
        "-0.95", "10", {ModifierScope.FISHING}, "Item rarity roll luck."
    ),
    StatKey.COOLDOWN_CHANGE_RATIO: _stat(
        "-0.80", "1.00", {ModifierScope.FISHING}, "Fishing cooldown change ratio."
    ),
    StatKey.EMPTY_CATCH_REROLL_CHANCE_PCT: _stat(
        "0", "1", {ModifierScope.FISHING}, "Chance to reroll an empty catch."
    ),
    StatKey.ROBBERY_PROTECTION_PCT: _stat(
        "0", "1", {ModifierScope.ROBBERY}, "Reduction of stolen mass."
    ),
    StatKey.ROBBERY_EVASION_PCT: _stat(
        "0", "1", {ModifierScope.ROBBERY}, "Reduction of robbery success chance."
    ),
    StatKey.PROTECTED_MASS_FLAT: _stat(
        "0", "1000000000000", {ModifierScope.ROBBERY, ModifierScope.FISHING},
        "Mass that cannot be removed.",
    ),
    StatKey.ROBBERY_COUNTER_CHANCE_PCT: _stat(
        "0", "1", {ModifierScope.ROBBERY}, "Chance to trigger a robbery counter."
    ),
    StatKey.ROBBERY_ATTACK_CHANCE_ADD: _stat(
        "-1", "1", {ModifierScope.ROBBERY}, "Additive robbery attack chance."
    ),
    StatKey.ROBBERY_AMOUNT_BONUS_PCT: _stat(
        "-0.95", "10", {ModifierScope.ROBBERY}, "Robbery amount bonus."
    ),
    StatKey.INVENTORY_SLOTS_ADD: _stat(
        "-100",
        "1000",
        {ModifierScope.INVENTORY},
        "Additional inventory slots.",
        value_type="integer",
    ),
    StatKey.SELL_RATE_BONUS_PCT: _stat(
        "-0.95", "10", {ModifierScope.ECONOMY}, "Fish selling rate bonus."
    ),
    StatKey.BUY_DISCOUNT_PCT: _stat(
        "0", "0.95", {ModifierScope.ECONOMY}, "Fish buying discount."
    ),
}


class StatEffectBase(StrictItemModel):
    stat: StatKey
    value: Decimal
    trigger: Literal["passive"] = "passive"

    @model_validator(mode="after")
    def validate_value(self):
        definition = STAT_REGISTRY[self.stat]
        if getattr(self, "type", None) == "stat_multiply":
            if self.value < 0 or self.value > 100:
                raise ValueError("Multiplier must be between 0 and 100")
            return self
        if (
            definition.value_type == "integer"
            and self.value != self.value.to_integral_value()
        ):
            raise ValueError(f"{self.stat.value} must be an integer")
        if not definition.minimum <= self.value <= definition.maximum:
            raise ValueError(
                f"{self.stat.value} must be between {definition.minimum} and {definition.maximum}"
            )
        return self


class StatAddEffect(StatEffectBase):
    type: Literal["stat_add"]


class StatMultiplyEffect(StatEffectBase):
    type: Literal["stat_multiply"]


class RerollRewardEffect(StrictItemModel):
    type: Literal["reroll_reward"]
    trigger: Literal["after_reward_roll"] = "after_reward_roll"
    target_action_types: list[str] = Field(min_length=1, max_length=20)
    max_rerolls: int = Field(1, ge=1, le=3)
    durability_cost: int = Field(0, ge=0, le=1000)


class BlockActionEffect(StrictItemModel):
    type: Literal["block_action"]
    trigger: Literal["after_reward_roll", "on_robbery_attempt"]
    target_action_types: list[str] = Field(min_length=1, max_length=20)
    chance: Decimal = Field(Decimal(1), ge=0, le=1)
    durability_cost: int = Field(0, ge=0, le=1000)


class TimeoutEffectAction(StrictItemModel):
    type: Literal["timeout"]
    duration_seconds: int = Field(..., ge=1, le=1_209_600)
    reason: str = Field("Item counter effect", max_length=200)
    message: str = Field("", max_length=300)


class MassEffectAction(StrictItemModel):
    type: Literal["add_mass"]
    mass: Decimal = Field(..., ge=-1_000_000, le=1_000_000)
    message: str = Field("", max_length=300)


CounterAction = Annotated[TimeoutEffectAction | MassEffectAction, Field(discriminator="type")]


class RobberyCounterEffect(StrictItemModel):
    type: Literal["robbery_counter"]
    trigger: Literal["on_robbery_attempt", "on_robbery_success"] = "on_robbery_attempt"
    chance: Decimal = Field(Decimal(1), ge=0, le=1)
    action: CounterAction
    durability_cost: int = Field(1, ge=0, le=1000)


class AbsorbRobberyEffect(StrictItemModel):
    type: Literal["absorb_robbery"]
    trigger: Literal["on_robbery_attempt"] = "on_robbery_attempt"
    chance: Decimal = Field(Decimal(1), ge=0, le=1)
    attacker_mass_delta: Decimal = Field(Decimal(0), ge=-1_000_000, le=1_000_000)
    message: str = Field("", max_length=300)
    durability_cost: int = Field(1, ge=0, le=1000)


class MassFloorEffect(StrictItemModel):
    type: Literal["mass_floor"]
    protected_mass: Decimal = Field(..., ge=0, le=1_000_000_000_000)
    scopes: list[Literal["robbery", "negative_rewards", "roulette"]] = Field(
        min_length=1, max_length=3
    )


class GrantItemEffect(StrictItemModel):
    type: Literal["grant_item"]
    item_id: str = Field(..., min_length=1, max_length=120)
    quantity: int = Field(1, ge=1, le=1_000_000)


class GrantMassEffect(StrictItemModel):
    type: Literal["grant_mass"]
    mass: Decimal = Field(..., ge=-1_000_000, le=1_000_000)


class ApplyTimeoutEffect(StrictItemModel):
    type: Literal["apply_timeout"]
    duration_seconds: int = Field(..., ge=1, le=1_209_600)
    reason: str = Field("Item effect", max_length=200)


class LootTableRollEffect(StrictItemModel):
    type: Literal["loot_table_roll"]
    loot_table_id: str = Field(..., min_length=1, max_length=120)
    rolls: int = Field(1, ge=1, le=20)


class ConsumeDurabilityEffect(StrictItemModel):
    """Durability consumption for equipped equipment (spec §11.4).

    Only valid on equipment; changes ``InventoryItem.current_durability``.
    """

    type: Literal["consume_durability"]
    trigger: Literal["after_cast", "after_successful_cast", "after_item_drop"]
    amount: int = Field(1, ge=1, le=1000)


class ConsumeChargeEffect(StrictItemModel):
    """Charge consumption for a charge-based consumable (spec §11.4).

    Only valid on a consumable with ``max_charges`` set; changes
    ``InventoryItem.current_charges``.
    """

    type: Literal["consume_charge"]
    trigger: Literal["after_cast", "after_successful_cast", "after_item_drop"]
    amount: int = Field(1, ge=1, le=1000)


ItemEffect = Annotated[
    StatAddEffect
    | StatMultiplyEffect
    | RerollRewardEffect
    | BlockActionEffect
    | RobberyCounterEffect
    | AbsorbRobberyEffect
    | MassFloorEffect
    | GrantItemEffect
    | GrantMassEffect
    | ApplyTimeoutEffect
    | LootTableRollEffect
    | ConsumeDurabilityEffect
    | ConsumeChargeEffect,
    Field(discriminator="type"),
]


# Compatibility matrix (plan §4): an effect is only valid on an item type
# when a runtime executor actually processes it there. Anything else would be a
# schema-valid no-op, so it is rejected at definition time.
_ITEM_TYPE_EFFECT_COMPATIBILITY: dict[str, frozenset[ItemType]] = {
    "stat_add": frozenset({ItemType.EQUIPMENT}),
    "stat_multiply": frozenset({ItemType.EQUIPMENT}),
    "reroll_reward": frozenset({ItemType.EQUIPMENT}),
    "block_action": frozenset({ItemType.EQUIPMENT}),
    "robbery_counter": frozenset({ItemType.EQUIPMENT}),
    "absorb_robbery": frozenset({ItemType.EQUIPMENT}),
    "mass_floor": frozenset({ItemType.EQUIPMENT}),
    "grant_item": frozenset({ItemType.CONSUMABLE, ItemType.LOOTBOX}),
    "grant_mass": frozenset({ItemType.CONSUMABLE, ItemType.LOOTBOX}),
    "apply_timeout": frozenset({ItemType.CONSUMABLE, ItemType.LOOTBOX}),
    "loot_table_roll": frozenset({ItemType.CONSUMABLE, ItemType.LOOTBOX}),
    "consume_durability": frozenset({ItemType.EQUIPMENT}),
    "consume_charge": frozenset({ItemType.CONSUMABLE}),
}


class ItemDefinitionData(StrictItemModel):
    item_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,119}$")
    title: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(None, max_length=1000)
    item_type: ItemType
    equipment_slot: EquipmentSlot | None = None
    rarity: ItemRarity = ItemRarity.COMMON
    stack_size: int = Field(1, ge=1, le=1_000_000)
    max_durability: int | None = Field(None, ge=1, le=1_000_000)
    max_charges: int | None = Field(None, ge=1, le=1_000_000)
    break_policy: BreakPolicy = BreakPolicy.INDESTRUCTIBLE
    schema_version: int = Field(1, ge=1, le=1000)
    effects: list[ItemEffect] = Field(default_factory=list, max_length=100)
    image_url: str | None = Field(None, max_length=2048)
    value: Decimal | None = Field(None, ge=0, le=1_000_000_000_000)

    @model_validator(mode="after")
    def validate_item_shape(self):
        if self.item_type == ItemType.EQUIPMENT:
            if self.equipment_slot is None:
                raise ValueError("equipment_slot is required for equipment")
            if self.stack_size != 1:
                raise ValueError("equipment must use stack_size 1")
            if self.max_charges is not None:
                raise ValueError("max_charges is only allowed for consumables")
        elif self.equipment_slot is not None:
            raise ValueError("equipment_slot is only allowed for equipment")
        if self.item_type != ItemType.CONSUMABLE and self.max_charges is not None:
            raise ValueError("max_charges is only allowed for consumables")
        if self.max_charges is not None and self.stack_size != 1:
            raise ValueError("charge-based consumables must use stack_size 1")
        if self.break_policy != BreakPolicy.INDESTRUCTIBLE and self.max_durability is None:
            raise ValueError("max_durability is required for breakable items")
        if self.max_durability is not None and self.item_type != ItemType.EQUIPMENT:
            raise ValueError("max_durability is only allowed for equipment")
        for effect in self.effects:
            effect_type = effect.type
            if effect_type == "grant_item" and effect.item_id == self.item_id:
                raise ValueError("An item cannot grant itself")
            if effect_type == "consume_durability":
                if self.item_type != ItemType.EQUIPMENT:
                    raise ValueError("consume_durability is only allowed for equipment")
                continue
            if effect_type == "consume_charge":
                if self.item_type != ItemType.CONSUMABLE:
                    raise ValueError("consume_charge is only allowed for consumables")
                if self.max_charges is None:
                    raise ValueError("consume_charge requires max_charges on the consumable")
                continue
            allowed_types = _ITEM_TYPE_EFFECT_COMPATIBILITY.get(effect_type)
            if allowed_types is None:
                raise ValueError(f"Unsupported effect type: {effect_type}")
            if self.item_type not in allowed_types:
                raise ValueError(
                    f"{effect_type} is not compatible with {self.item_type.value}"
                )
        return self


def validate_stat_value(stat: StatKey, value: Decimal) -> Decimal:
    definition = STAT_REGISTRY[stat]
    if definition.value_type == "integer" and value != value.to_integral_value():
        raise ValueError(f"{stat.value} must be an integer")
    if not definition.minimum <= value <= definition.maximum:
        raise ValueError(
            f"{stat.value} must be between {definition.minimum} and {definition.maximum}"
        )
    return value
