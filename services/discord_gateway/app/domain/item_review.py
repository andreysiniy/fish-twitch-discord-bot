"""Item compatibility validation for the review screen (wizard spec §36/§37/§65).

Pure domain logic, no Discord objects. ``compatibility_issues`` classifies a
draft into blocking errors (Confirm stays disabled until fixed) and non-blocking
warnings. The rules mirror the backend ``ItemDefinitionData`` invariants plus the
review-only warnings from spec §65; the backend remains the final authority
(spec §36/§66).
"""

from decimal import Decimal
from typing import Any

from app.domain.item_effect_registry import effect_identity, effect_label

# A loot box must produce at least one of these to be worth opening (spec §37).
LOOT_PRODUCING_EFFECTS = frozenset({"loot_table_roll", "grant_item"})

# A passive fish luck bonus above this ratio (100%) triggers the "very large
# fishing bonus" review warning (spec §65).
LARGE_FISH_LUCK_RATIO = Decimal("1")

_EQUIPMENT_TYPES = frozenset({"equipment"})
_CONSUMABLE_TYPES = frozenset({"consumable"})
_LOOTBOX_TYPES = frozenset({"lootbox"})
_PASSIVE_STAT_EFFECTS = frozenset({"stat_add", "stat_multiply"})

# Effect / item-type compatibility mirror (plan §4): an effect is only valid on
# an item type that has a runtime executor. The backend re-validates on submit
# and is the authority; this mirror keeps Confirm disabled for drafts the
# backend would reject.
_EQUIPMENT_ONLY_EFFECTS = frozenset(
    {
        "stat_add",
        "stat_multiply",
        "reroll_reward",
        "block_action",
        "robbery_counter",
        "absorb_robbery",
        "mass_floor",
        "consume_durability",
    }
)
_USE_ONLY_EFFECTS = frozenset(
    {"grant_item", "grant_mass", "apply_timeout", "loot_table_roll"}
)


def _effect_types(effects: list[dict[str, Any]]) -> list[str]:
    return [str(effect.get("type") or "") for effect in effects]


def _fishing_luck_total(effects: list[dict[str, Any]]) -> Decimal:
    """Sum of passive fish luck bonuses; used for the large-bonus warning."""
    total = Decimal("0")
    for effect in effects:
        if effect.get("type") != "stat_add":
            continue
        if effect.get("stat") != "fish_luck_change_ratio":
            continue
        try:
            total += Decimal(str(effect.get("value")))
        except Exception:
            continue
    return total


def compatibility_issues(draft: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Split a draft into ``(blocking_errors, warnings)`` (spec §36/§37/§65).

    Blocking errors disable the Confirm button; warnings are informational and
    never block saving (spec §65). The draft is only a UI suggestion; the
    backend re-validates everything on submit.
    """
    item_type = str(draft.get("item_type") or "material")
    equipment_slot = draft.get("equipment_slot")
    max_durability = draft.get("max_durability")
    max_charges = draft.get("max_charges")
    break_policy = str(draft.get("break_policy") or "indestructible")
    stack_size = draft.get("stack_size", 1)
    effects = list(draft.get("effects") or [])
    effect_type_list = _effect_types(effects)

    errors: list[str] = []
    warnings: list[str] = []

    # Slot / durability / charges / break-behavior ownership (spec §36/§11.4).
    if item_type not in _EQUIPMENT_TYPES and equipment_slot:
        errors.append("This item type does not support an equipment slot.")
    if item_type not in _EQUIPMENT_TYPES and max_durability:
        errors.append("Only equipment items can use durability.")
    if item_type not in _EQUIPMENT_TYPES and break_policy != "indestructible":
        errors.append("Only equipment items can have a break behavior.")
    if item_type != "consumable" and max_charges:
        errors.append("Only consumables can carry a maximum charge count.")
    if max_charges and int(stack_size or 1) != 1:
        errors.append("Charge-based consumables must use stack size 1.")

    # Equipment invariants (spec §8/§36).
    if item_type in _EQUIPMENT_TYPES:
        if not equipment_slot:
            errors.append("Equipment must have an equipment slot.")
        if int(stack_size or 1) != 1:
            errors.append("Equipment must use stack size 1.")
        if break_policy != "indestructible" and not max_durability:
            errors.append("Maximum Durability is required for breakable equipment.")
        if not effects:
            warnings.append("This equipment has no effects and will not change gameplay.")

    # Empty effects policy (spec §37).
    if item_type in _CONSUMABLE_TYPES and not effects:
        errors.append("A consumable must have at least one usable effect.")
    if item_type in _LOOTBOX_TYPES:
        if not effects:
            errors.append("A loot box must contain at least one loot table roll or grant effect.")
        elif not any(effect_type in LOOT_PRODUCING_EFFECTS for effect_type in effect_type_list):
            errors.append("A loot box must contain at least one loot table roll or grant effect.")

    # Effect compatibility (spec §36/§11.4 + plan §4 matrix).
    seen_effects: set[tuple[str, str | None]] = set()
    for effect in effects:
        effect_type = str(effect.get("type") or "")
        identity = effect_identity(effect)
        if identity in seen_effects:
            errors.append(f"Duplicate effect is not allowed: {effect_label(effect_type)}.")
        seen_effects.add(identity)
        if effect_type == "consume_durability":
            if item_type not in _EQUIPMENT_TYPES:
                errors.append("Consume Durability is only compatible with equipment.")
            elif break_policy == "indestructible":
                warnings.append("This effect consumes durability, but the item is indestructible.")
        if effect_type == "consume_charge":
            if item_type not in _CONSUMABLE_TYPES:
                errors.append("Consume Charge is only compatible with a consumable.")
            elif not max_charges:
                errors.append("Consume Charge requires a maximum charge count on the consumable.")
        if effect_type in _EQUIPMENT_ONLY_EFFECTS and item_type not in _EQUIPMENT_TYPES:
            errors.append(
                f"{effect_label(effect_type)} is only compatible with equipment."
            )
        if effect_type in _USE_ONLY_EFFECTS and item_type not in _CONSUMABLE_TYPES | _LOOTBOX_TYPES:
            errors.append(
                f"{effect_label(effect_type)} is only compatible with consumables and loot boxes."
            )
        if item_type in _LOOTBOX_TYPES and effect_type == "grant_item":
            if effect.get("item_id") == draft.get("item_id"):
                warnings.append(
                    "This loot box can grant an item that eventually grants this loot box again."
                )

    # Large fishing bonus warning (spec §65).
    if _fishing_luck_total(effects) > LARGE_FISH_LUCK_RATIO:
        warnings.append("This item provides a very large fishing bonus.")

    return errors, warnings
