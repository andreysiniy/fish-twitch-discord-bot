"""Human-facing item effect registry (wizard spec §12/§14-§20/§21-§33/§51).

Declarative vocabulary for building and describing item effects in the Discord
UI without exposing backend identifiers:

- ``UI_STAT_DEFINITIONS`` maps every backend StatKey to a human label, unit,
  category, helper text and display bounds (spec §51).
- ``EFFECT_CATEGORIES`` is the category select shown on the effects screen
  (spec §12).
- ``TRIGGERED_EFFECT_FORMS`` describes each triggered effect as a data-driven
  form: which fields are selects/multiselects/entity references and which are
  collected through a modal (spec §22-§31).
- ``describe_effect`` renders any draft effect as one human-readable line
  (spec §13): never raw ``stat_add: fish_luck_change_ratio = 0.10`` text.

The registry is the only place that knows this vocabulary; the modals in
``effect_forms.py`` and the ``ItemEffectsView`` in ``effects.py`` consume it.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.domain.percent_helpers import probability_to_percentage_points, ratio_to_percent

# Unit of a stat value. ``percent`` and ``percentage_points`` are stored as
# backend ratios (÷100); ``mass_kg`` and ``flat`` are stored verbatim.
UNIT_PERCENT = "percent"
UNIT_PERCENTAGE_POINTS = "percentage_points"
UNIT_MASS_KG = "mass_kg"
UNIT_FLAT = "flat"

# Effect-count limits (spec §35). The standard editor caps the list at 10 so
# it stays manageable in a Discord select; the advanced editor (entered through
# the §32 warning) allows 25. The backend may accept more for legacy/imported
# items, but the standard UI must not create items that cannot be managed
# through the select-based editor.
STANDARD_MAX_EFFECTS = 10
ADVANCED_MAX_EFFECTS = 25

# Effect categories shown on the effects screen (spec §12).
CATEGORY_FISHING = "fishing"
CATEGORY_ITEM_DROP = "item_drop"
CATEGORY_ROBBERY = "robbery"
CATEGORY_INVENTORY = "inventory"
CATEGORY_ECONOMY = "economy"
CATEGORY_TRIGGERED = "triggered"
CATEGORY_ADVANCED = "advanced"

EFFECT_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("Fishing Bonus", CATEGORY_FISHING),
    ("Item Drop Bonus", CATEGORY_ITEM_DROP),
    ("Robbery Bonus", CATEGORY_ROBBERY),
    ("Inventory Bonus", CATEGORY_INVENTORY),
    ("Economy Bonus", CATEGORY_ECONOMY),
    ("Triggered Effect", CATEGORY_TRIGGERED),
    ("Advanced Effect", CATEGORY_ADVANCED),
)


@dataclass(frozen=True)
class UIStatDefinition:
    """One entry in the UI stat registry (spec §51)."""

    stat: str
    label: str
    category: str
    unit: str
    input_label: str
    helper: str
    display_min: str | None
    display_max: str | None
    value_type: str = "decimal"
    scope: str = "fishing"


def _percent_stat(
    stat: str,
    label: str,
    category: str,
    helper: str,
    ratio_min: str,
    ratio_max: str,
    scope: str = "fishing",
) -> UIStatDefinition:
    return UIStatDefinition(
        stat=stat,
        label=label,
        category=category,
        unit=UNIT_PERCENT,
        input_label="Change, %",
        helper=helper,
        display_min=_ratio_to_display(ratio_min, UNIT_PERCENT),
        display_max=_ratio_to_display(ratio_max, UNIT_PERCENT),
        scope=scope,
    )


def _ratio_to_display(value: str, unit: str) -> str:
    number = Decimal(value)
    if unit == UNIT_PERCENT:
        number = ratio_to_percent(number)
    elif unit == UNIT_PERCENTAGE_POINTS:
        number = probability_to_percentage_points(number)
    return _format_display(number)


def _format_display(value: Decimal) -> str:
    if value == value.to_integral_value():
        return f"{int(value)}"
    return format(value, "f").rstrip("0").rstrip(".")


def _flat_stat(
    stat: str,
    label: str,
    category: str,
    input_label: str,
    helper: str,
    display_min: str,
    display_max: str,
    scope: str,
    value_type: str = "decimal",
) -> UIStatDefinition:
    return UIStatDefinition(
        stat=stat,
        label=label,
        category=category,
        unit=UNIT_FLAT,
        input_label=input_label,
        helper=helper,
        display_min=display_min,
        display_max=display_max,
        value_type=value_type,
        scope=scope,
    )


def _kg_stat(
    stat: str,
    label: str,
    category: str,
    input_label: str,
    helper: str,
    display_min: str,
    display_max: str,
    scope: str,
) -> UIStatDefinition:
    return UIStatDefinition(
        stat=stat,
        label=label,
        category=category,
        unit=UNIT_MASS_KG,
        input_label=input_label,
        helper=helper,
        display_min=display_min,
        display_max=display_max,
        scope=scope,
    )


# --- UI stat registry (spec §14-§20/§51) --------------------------------------
# Values mirror game_engine STAT_REGISTRY; display bounds are human units.

UI_STAT_DEFINITIONS: dict[str, UIStatDefinition] = {
    # Fishing Bonus (spec §14)
    "fish_luck_change_ratio": _percent_stat(
        "fish_luck_change_ratio",
        "Fish Luck",
        CATEGORY_FISHING,
        "Positive values make catches heavier; negative values make them lighter.",
        "-0.50",
        "1.00",
    ),
    "positive_fish_reward_change_ratio": _percent_stat(
        "positive_fish_reward_change_ratio",
        "Positive Fish Reward",
        CATEGORY_FISHING,
        "Positive values increase how much you gain from successful catches.",
        "-0.50",
        "2.00",
    ),
    "negative_fish_reward_change_ratio": _percent_stat(
        "negative_fish_reward_change_ratio",
        "Negative Fish Reward",
        CATEGORY_FISHING,
        "Use a negative value to make bad catches less severe. "
        "Example: -20 means a 20% softer penalty.",
        "-1.00",
        "1.00",
    ),
    "xp_gain_change_ratio": _percent_stat(
        "xp_gain_change_ratio",
        "Fishing XP",
        CATEGORY_FISHING,
        "Positive values increase XP gained from casts.",
        "-1.00",
        "4.00",
    ),
    "cooldown_change_ratio": _percent_stat(
        "cooldown_change_ratio",
        "Fishing Cooldown",
        CATEGORY_FISHING,
        "Use a negative value to reduce the cooldown. Example: -10 means a 10% shorter cooldown.",
        "-0.80",
        "1.00",
    ),
    "empty_catch_reroll_chance_pct": _percent_stat(
        "empty_catch_reroll_chance_pct",
        "Empty Catch Reroll Chance",
        CATEGORY_FISHING,
        "Chance to reroll an empty catch.",
        "0",
        "1",
    ),
    # Item Drop Bonus (spec §17)
    "item_drop_chance_add": UIStatDefinition(
        stat="item_drop_chance_add",
        label="Item Drop Chance",
        category=CATEGORY_ITEM_DROP,
        unit=UNIT_PERCENTAGE_POINTS,
        input_label="Change, percentage points",
        helper="Percentage points, not relative percent. "
        "Example: 0.5 changes a 6% base drop chance to 6.5%.",
        display_min="-100",
        display_max="100",
    ),
    "item_rarity_luck_pct": _percent_stat(
        "item_rarity_luck_pct",
        "Item Rarity Luck",
        CATEGORY_ITEM_DROP,
        "Increases the chance of rarer items when an item drops.",
        "-0.95",
        "10",
    ),
    # Robbery Bonus (spec §18)
    "robbery_protection_pct": _percent_stat(
        "robbery_protection_pct",
        "Robbery Protection",
        CATEGORY_ROBBERY,
        "Reduces how much mass a robbery can take.",
        "0",
        "1",
        scope="robbery",
    ),
    "robbery_evasion_pct": _percent_stat(
        "robbery_evasion_pct",
        "Robbery Evasion",
        CATEGORY_ROBBERY,
        "Reduces the chance a robbery against you succeeds.",
        "0",
        "1",
        scope="robbery",
    ),
    "protected_mass_flat": _kg_stat(
        "protected_mass_flat",
        "Protected Mass",
        CATEGORY_ROBBERY,
        "Protected Mass, kg",
        "Mass that cannot be removed by robbery or negative rewards.",
        "0",
        "1000000000000",
        scope="robbery",
    ),
    "robbery_counter_chance_pct": _percent_stat(
        "robbery_counter_chance_pct",
        "Robbery Counter Chance",
        CATEGORY_ROBBERY,
        "Chance to counter an incoming robbery.",
        "0",
        "1",
        scope="robbery",
    ),
    "robbery_attack_chance_add": _percent_stat(
        "robbery_attack_chance_add",
        "Robbery Attack Chance",
        CATEGORY_ROBBERY,
        "Changes the chance of a robbery you launch succeeding.",
        "-1",
        "1",
        scope="robbery",
    ),
    "robbery_amount_bonus_pct": _percent_stat(
        "robbery_amount_bonus_pct",
        "Robbery Amount",
        CATEGORY_ROBBERY,
        "Increases or reduces how much mass a robbery takes.",
        "-0.95",
        "10",
        scope="robbery",
    ),
    # Inventory Bonus (spec §19)
    "inventory_slots_add": _flat_stat(
        "inventory_slots_add",
        "Inventory Slots",
        CATEGORY_INVENTORY,
        "Additional Slots",
        "Extra inventory slots granted by this item.",
        "-100",
        "1000",
        scope="inventory",
        value_type="integer",
    ),
    # Economy Bonus (spec §20)
    "sell_rate_bonus_pct": _percent_stat(
        "sell_rate_bonus_pct",
        "Sell Rate",
        CATEGORY_ECONOMY,
        "Increases or reduces the price fish are sold for.",
        "-0.95",
        "10",
        scope="economy",
    ),
    "buy_discount_pct": _percent_stat(
        "buy_discount_pct",
        "Buy Discount",
        CATEGORY_ECONOMY,
        "Discount applied when buying.",
        "0",
        "0.95",
        scope="economy",
    ),
    # Advanced-only stats (spec §33): reachable only through the advanced
    # editor, never through the standard category selects.
    "points_flat_bonus": _flat_stat(
        "points_flat_bonus",
        "Points",
        CATEGORY_ADVANCED,
        "Points, flat",
        "Flat points reward adjustment.",
        "-1000000",
        "1000000",
        scope="fishing",
        value_type="integer",
    ),
}

# Stats that exist in the backend but are only reachable through the advanced
# effect editor (spec §33 keeps risky/rarely-used stats out of the standard UI).
ADVANCED_ONLY_STATS: tuple[str, ...] = ("points_flat_bonus",)

STAT_DEFINITIONS_BY_CATEGORY: dict[str, list[UIStatDefinition]] = {
    CATEGORY_FISHING: [],
    CATEGORY_ITEM_DROP: [],
    CATEGORY_ROBBERY: [],
    CATEGORY_INVENTORY: [],
    CATEGORY_ECONOMY: [],
    CATEGORY_ADVANCED: [],
}
for _definition in UI_STAT_DEFINITIONS.values():
    STAT_DEFINITIONS_BY_CATEGORY.setdefault(_definition.category, []).append(_definition)

# The advanced editor offers every stat (standard categories plus the
# advanced-only stats), one entry per stat, sorted by label.
_ADVANCED_UNIQUE: dict[str, UIStatDefinition] = {
    stat: UI_STAT_DEFINITIONS[stat] for stat in ADVANCED_ONLY_STATS if stat in UI_STAT_DEFINITIONS
}
_ADVANCED_UNIQUE.update(
    {
        stat: definition
        for stat, definition in UI_STAT_DEFINITIONS.items()
        if definition.category != CATEGORY_ADVANCED
    }
)
ADVANCED_STAT_DEFINITIONS: list[UIStatDefinition] = sorted(
    _ADVANCED_UNIQUE.values(), key=lambda definition: definition.label
)


def stat_options(category: str) -> list[UIStatDefinition]:
    if category == CATEGORY_ADVANCED:
        return ADVANCED_STAT_DEFINITIONS
    return list(STAT_DEFINITIONS_BY_CATEGORY.get(category, []))


# --- triggered effect forms (spec §22-§31) ------------------------------------


@dataclass(frozen=True)
class EffectField:
    """One field of a triggered effect form.

    ``kind`` is one of:
    - ``select``: single choice from ``options``;
    - ``multiselect``: multiple choices from ``options``;
    - ``entity``: reference chosen from a channel-scoped list (items/loot tables);
    - ``number`` / ``text``: collected through the effect numbers modal.
    """

    key: str
    kind: str
    label: str
    options: tuple[tuple[str, str], ...] = ()
    entity: str | None = None
    min_values: int = 1
    max_values: int = 1
    required: bool = True
    min: int | Decimal | None = None
    max: int | Decimal | None = None
    default: Any = None
    unit: str | None = None
    placeholder: str | None = None

    @property
    def is_modal_field(self) -> bool:
        return self.kind in ("number", "text")


@dataclass(frozen=True)
class EffectForm:
    type: str
    label: str
    description: str
    defaults: dict[str, Any]
    fields: tuple[EffectField, ...]


REROLL_TARGET_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Empty Catch", "nothing"),
    ("Negative Mass Reward", "negative_mass"),
    ("Negative Percentage Reward", "negative_percentage"),
    ("Robbery", "robbery"),
    ("Timeout", "timeout"),
)

TRIGGER_REWARD_OPTIONS: tuple[tuple[str, str], ...] = (
    ("After Reward Roll", "after_reward_roll"),
    ("On Robbery Attempt", "on_robbery_attempt"),
)

ROBBERY_COUNTER_TRIGGER_OPTIONS: tuple[tuple[str, str], ...] = (
    ("On Robbery Attempt", "on_robbery_attempt"),
    ("On Robbery Success", "on_robbery_success"),
)

COUNTER_ACTION_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Apply Timeout", "timeout"),
    ("Change Attacker Mass", "add_mass"),
)

CONSUME_TRIGGER_OPTIONS: tuple[tuple[str, str], ...] = (
    ("After Any Cast", "after_cast"),
    ("After a Successful Cast", "after_successful_cast"),
    ("After an Item Drop", "after_item_drop"),
)

MASS_FLOOR_SCOPE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Robbery", "robbery"),
    ("Negative Fish Rewards", "negative_rewards"),
    ("Roulette", "roulette"),
)

TRIGGERED_EFFECT_FORMS: dict[str, EffectForm] = {
    "reroll_reward": EffectForm(
        type="reroll_reward",
        label="Reroll a Reward",
        description="Rerolls a caught reward when it matches the target actions.",
        defaults={"trigger": "after_reward_roll"},
        fields=(
            EffectField(
                key="target_action_types",
                kind="multiselect",
                label="Target actions",
                options=REROLL_TARGET_OPTIONS,
                min_values=1,
                max_values=5,
            ),
            EffectField(
                key="max_rerolls",
                kind="number",
                label="Maximum Rerolls",
                min=1,
                max=3,
                default=1,
            ),
            EffectField(
                key="durability_cost",
                kind="number",
                label="Durability Cost",
                min=0,
                max=1000,
                default=0,
            ),
        ),
    ),
    "block_action": EffectForm(
        type="block_action",
        label="Block an Action",
        description="Blocks a matching action with a chance before it resolves.",
        defaults={},
        fields=(
            EffectField(
                key="trigger",
                kind="select",
                label="Trigger",
                options=TRIGGER_REWARD_OPTIONS,
            ),
            EffectField(
                key="target_action_types",
                kind="multiselect",
                label="Target actions",
                options=REROLL_TARGET_OPTIONS,
                min_values=1,
                max_values=5,
            ),
            EffectField(
                key="chance",
                kind="number",
                label="Chance, %",
                unit=UNIT_PERCENT,
                min=0,
                max=100,
                default=100,
            ),
            EffectField(
                key="durability_cost",
                kind="number",
                label="Durability Cost",
                min=0,
                max=1000,
                default=0,
            ),
        ),
    ),
    "robbery_counter": EffectForm(
        type="robbery_counter",
        label="Counter a Robbery",
        description="Counters an incoming robbery with a timeout or a mass change.",
        defaults={},
        fields=(
            EffectField(
                key="trigger",
                kind="select",
                label="Trigger",
                options=ROBBERY_COUNTER_TRIGGER_OPTIONS,
            ),
            EffectField(
                key="chance",
                kind="number",
                label="Chance, %",
                unit=UNIT_PERCENT,
                min=0,
                max=100,
                default=100,
            ),
            EffectField(
                key="action_type",
                kind="select",
                label="Counter action",
                options=COUNTER_ACTION_OPTIONS,
            ),
            EffectField(
                key="duration_seconds",
                kind="number",
                label="Timeout Duration, seconds",
                min=1,
                max=1_209_600,
                default=60,
            ),
            EffectField(
                key="attacker_mass_delta",
                kind="number",
                label="Attacker Mass Change, kg",
                unit=UNIT_MASS_KG,
                min=-1_000_000,
                max=1_000_000,
                default=0,
            ),
            EffectField(
                key="durability_cost",
                kind="number",
                label="Durability Cost",
                min=0,
                max=1000,
                default=1,
            ),
        ),
    ),
    "absorb_robbery": EffectForm(
        type="absorb_robbery",
        label="Absorb a Robbery",
        description="Absorbs an attempted robbery and optionally shifts attacker mass.",
        defaults={"trigger": "on_robbery_attempt"},
        fields=(
            EffectField(
                key="chance",
                kind="number",
                label="Chance, %",
                unit=UNIT_PERCENT,
                min=0,
                max=100,
                default=100,
            ),
            EffectField(
                key="attacker_mass_delta",
                kind="number",
                label="Attacker Mass Change, kg",
                unit=UNIT_MASS_KG,
                min=-1_000_000,
                max=1_000_000,
                default=0,
            ),
            EffectField(
                key="durability_cost",
                kind="number",
                label="Durability Cost",
                min=0,
                max=1000,
                default=1,
            ),
        ),
    ),
    "mass_floor": EffectForm(
        type="mass_floor",
        label="Protect Minimum Mass",
        description="Protects a minimum mass floor from reductions in the chosen scopes.",
        defaults={},
        fields=(
            EffectField(
                key="protected_mass",
                kind="number",
                label="Protected Mass, kg",
                unit=UNIT_MASS_KG,
                min=0,
                max=1_000_000_000_000,
            ),
            EffectField(
                key="scopes",
                kind="multiselect",
                label="Scopes",
                options=MASS_FLOOR_SCOPE_OPTIONS,
                min_values=1,
                max_values=3,
            ),
        ),
    ),
    "grant_item": EffectForm(
        type="grant_item",
        label="Grant an Item",
        description="Grants a quantity of another item from this channel.",
        defaults={},
        fields=(
            EffectField(
                key="item_id",
                kind="entity",
                label="Item",
                entity="items",
            ),
            EffectField(
                key="quantity",
                kind="number",
                label="Quantity",
                min=1,
                max=1_000_000,
                default=1,
            ),
        ),
    ),
    "grant_mass": EffectForm(
        type="grant_mass",
        label="Grant Mass",
        description="Grants a flat mass amount.",
        defaults={},
        fields=(
            EffectField(
                key="mass",
                kind="number",
                label="Mass Change, kg",
                unit=UNIT_MASS_KG,
                min=-1_000_000,
                max=1_000_000,
            ),
        ),
    ),
    "apply_timeout": EffectForm(
        type="apply_timeout",
        label="Apply Timeout",
        description="Applies a timeout with a reason.",
        defaults={},
        fields=(
            EffectField(
                key="duration_seconds",
                kind="number",
                label="Duration, seconds",
                min=1,
                max=1_209_600,
            ),
            EffectField(
                key="reason",
                kind="text",
                label="Reason",
                default="Item effect",
                placeholder="Why the timeout is applied",
            ),
        ),
    ),
    "loot_table_roll": EffectForm(
        type="loot_table_roll",
        label="Roll a Loot Table",
        description="Rolls a loot table from this channel.",
        defaults={},
        fields=(
            EffectField(
                key="loot_table_id",
                kind="entity",
                label="Loot Table",
                entity="loot_tables",
            ),
            EffectField(
                key="rolls",
                kind="number",
                label="Rolls",
                min=1,
                max=20,
                default=1,
            ),
        ),
    ),
    "consume_durability": EffectForm(
        type="consume_durability",
        label="Consume Durability",
        description="Consumes durability from equipped equipment after a trigger.",
        defaults={},
        fields=(
            EffectField(
                key="trigger",
                kind="select",
                label="Trigger",
                options=CONSUME_TRIGGER_OPTIONS,
            ),
            EffectField(
                key="amount",
                kind="number",
                label="Amount",
                min=1,
                max=1000,
                default=1,
            ),
        ),
    ),
    "consume_charge": EffectForm(
        type="consume_charge",
        label="Consume Charge",
        description="Consumes a charge from a charge-based consumable after a trigger.",
        defaults={},
        fields=(
            EffectField(
                key="trigger",
                kind="select",
                label="Trigger",
                options=CONSUME_TRIGGER_OPTIONS,
            ),
            EffectField(
                key="amount",
                kind="number",
                label="Amount",
                min=1,
                max=1000,
                default=1,
            ),
        ),
    ),
}

TRIGGERED_EFFECT_OPTIONS: tuple[tuple[str, str], ...] = tuple(
    (form.label, form_key) for form_key, form in TRIGGERED_EFFECT_FORMS.items()
)


def effect_label(effect_type: str) -> str:
    """Human label for an effect type (no raw backend identifiers)."""
    if effect_type in ("stat_add", "stat_multiply"):
        return "Add Stat" if effect_type == "stat_add" else "Multiply Stat"
    form = TRIGGERED_EFFECT_FORMS.get(effect_type)
    if form is not None:
        return form.label
    return effect_type.replace("_", " ").title()


# --- human-readable effect descriptions (spec §13) ----------------------------


def describe_effect(effect: dict[str, Any]) -> str:
    """One human-readable line for a draft effect (spec §13/§70).

    Never renders backend stat keys, ratio decimals, or raw effect type names.
    """
    effect_type = str(effect.get("type") or "?")
    if effect_type == "stat_add":
        return _describe_stat_add(effect)
    if effect_type == "stat_multiply":
        return _describe_stat_multiply(effect)
    if effect_type == "grant_item":
        item_id = effect.get("item_id") or "?"
        quantity = effect.get("quantity", 1)
        return f"Grant Item: {item_id} ×{quantity}"
    if effect_type == "grant_mass":
        return f"Grant Mass: {_number(effect.get('mass'))} kg"
    if effect_type == "apply_timeout":
        return f"Apply Timeout: {_format_duration(int(effect.get('duration_seconds', 0)))}"
    if effect_type == "reroll_reward":
        targets = _join_options(effect.get("target_action_types") or [], REROLL_TARGET_OPTIONS)
        return f"Reroll Reward: {targets or '?'} (max {effect.get('max_rerolls', 1)})"
    if effect_type == "block_action":
        targets = _join_options(effect.get("target_action_types") or [], REROLL_TARGET_OPTIONS)
        chance = _percent_text(effect.get("chance"))
        return f"Block Action: {targets or '?'} ({chance})"
    if effect_type == "robbery_counter":
        chance = _percent_text(effect.get("chance"))
        action = effect.get("action") or {}
        detail = ""
        if action.get("type") == "timeout":
            detail = f" → {_format_duration(int(action.get('duration_seconds', 0)))}"
        elif action.get("type") == "add_mass":
            detail = f" → {_number(action.get('mass'))} kg"
        return f"Counter a Robbery ({chance}){detail}"
    if effect_type == "absorb_robbery":
        return f"Absorb a Robbery ({_percent_text(effect.get('chance'))})"
    if effect_type == "mass_floor":
        scopes = _join_options(effect.get("scopes") or [], MASS_FLOOR_SCOPE_OPTIONS)
        return f"Protect Minimum Mass: {_number(effect.get('protected_mass'))} kg ({scopes})"
    if effect_type == "loot_table_roll":
        table = effect.get("loot_table_id") or "?"
        return f"Roll Loot Table: {table} ×{effect.get('rolls', 1)}"
    if effect_type == "consume_durability":
        trigger = _join_options([effect.get("trigger")], CONSUME_TRIGGER_OPTIONS)
        return f"Consume Durability: {effect.get('amount', 1)} {trigger}"
    if effect_type == "consume_charge":
        trigger = _join_options([effect.get("trigger")], CONSUME_TRIGGER_OPTIONS)
        return f"Consume Charge: {effect.get('amount', 1)} {trigger}"
    return effect_type


def _describe_stat_add(effect: dict[str, Any]) -> str:
    stat = str(effect.get("stat") or "")
    definition = UI_STAT_DEFINITIONS.get(stat)
    if definition is None:
        return f"Stat: {stat} = {_number(effect.get('value'))}"
    value = effect.get("value")
    if definition.unit == UNIT_PERCENT:
        return f"{definition.label}: {_percent_text(value)}"
    if definition.unit == UNIT_PERCENTAGE_POINTS:
        return f"{definition.label}: {_signed_points(value)} percentage points"
    if definition.unit == UNIT_MASS_KG:
        return f"{definition.label}: {_number(value)} kg"
    return f"{definition.label}: {_signed(value)}"


def _describe_stat_multiply(effect: dict[str, Any]) -> str:
    stat = str(effect.get("stat") or "")
    definition = UI_STAT_DEFINITIONS.get(stat)
    label = definition.label if definition is not None else stat.replace("_", " ").title()
    return f"Multiply {label} by ×{_number(effect.get('value'))}"


def _percent_text(value: Any) -> str:
    """Render a backend ratio as a human percentage string."""
    number = _decimal(value)
    if number is None:
        return "?"
    percent = ratio_to_percent(number)
    sign = "+" if percent > 0 else ""
    return f"{sign}{_format_display(percent)}%"


def _signed(value: Any) -> str:
    number = _decimal(value)
    if number is None:
        return "?"
    sign = "+" if number > 0 else ""
    return f"{sign}{_format_display(number)}"


def _signed_points(value: Any) -> str:
    number = _decimal(value)
    if number is None:
        return "?"
    points = probability_to_percentage_points(number)
    sign = "+" if points > 0 else ""
    return f"{sign}{_format_display(points)}"


def _number(value: Any) -> str:
    number = _decimal(value)
    return "?" if number is None else _format_display(number)


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _join_options(values: list[Any], options: tuple[tuple[str, str], ...]) -> str:
    by_value = {value: label for label, value in options}
    labels = [by_value.get(str(item), str(item)) for item in values]
    return ", ".join(labels) if labels else ""


def _format_duration(total_seconds: int) -> str:
    """Format a duration in seconds as a human string (spec §29)."""
    if total_seconds <= 0:
        return "0 seconds"
    if total_seconds % 3600 == 0:
        hours = total_seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if total_seconds % 60 == 0:
        minutes = total_seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{total_seconds} seconds"


__all__ = [
    "UNIT_PERCENT",
    "UNIT_PERCENTAGE_POINTS",
    "UNIT_MASS_KG",
    "UNIT_FLAT",
    "STANDARD_MAX_EFFECTS",
    "ADVANCED_MAX_EFFECTS",
    "CATEGORY_FISHING",
    "CATEGORY_ITEM_DROP",
    "CATEGORY_ROBBERY",
    "CATEGORY_INVENTORY",
    "CATEGORY_ECONOMY",
    "CATEGORY_TRIGGERED",
    "CATEGORY_ADVANCED",
    "EFFECT_CATEGORIES",
    "UI_STAT_DEFINITIONS",
    "STAT_DEFINITIONS_BY_CATEGORY",
    "ADVANCED_STAT_DEFINITIONS",
    "ADVANCED_ONLY_STATS",
    "stat_options",
    "UIStatDefinition",
    "EffectField",
    "EffectForm",
    "REROLL_TARGET_OPTIONS",
    "TRIGGER_REWARD_OPTIONS",
    "ROBBERY_COUNTER_TRIGGER_OPTIONS",
    "COUNTER_ACTION_OPTIONS",
    "CONSUME_TRIGGER_OPTIONS",
    "MASS_FLOOR_SCOPE_OPTIONS",
    "TRIGGERED_EFFECT_FORMS",
    "TRIGGERED_EFFECT_OPTIONS",
    "effect_label",
    "describe_effect",
]
