"""Item creation/editing wizard helpers (UI audit §5.1/§9).

The primary item flow builds a draft in memory and lets the admin assemble
effects with the typed effect builder — no raw ``effects_json`` required.
"""

from typing import Any

from app.interactions.effect_builder import describe_effect

EQUIPMENT_SLOTS = {"rod", "bait", "defense", "storage", "charm_1", "charm_2"}
VALID_TYPES = {
    "equipment",
    "consumable",
    "lootbox",
    "material",
    "quest",
    "currency",
    "collectible",
}
VALID_RARITIES = {"common", "rare", "epic", "legendary"}


def normalize_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Normalise type-dependent fields to a valid backend item payload.

    ``schema_version``, ``image_url``, ``value`` and ``expected_version`` are
    carried over from the draft when present so the create/edit payload builder
    never silently resets them (wizard spec §53/§73.1). Create defaults are
    only applied when the draft does not already carry the value.
    """
    item_type = draft.get("item_type", "material")
    equipment_slot = draft.get("equipment_slot") if item_type == "equipment" else None
    stack_size = int(draft.get("stack_size", 1))
    if item_type == "equipment":
        stack_size = 1
    break_policy = draft.get("break_policy", "indestructible")
    max_durability = draft.get("max_durability")
    if break_policy == "indestructible":
        max_durability = None
    payload = {
        "item_id": str(draft.get("item_id", "")).strip().lower(),
        "title": str(draft.get("title", "")).strip(),
        "description": draft.get("description") or None,
        "item_type": item_type,
        "equipment_slot": equipment_slot,
        "rarity": draft.get("rarity", "common"),
        "stack_size": stack_size,
        "max_durability": max_durability,
        "break_policy": break_policy,
        "schema_version": draft.get("schema_version", 1),
        "effects": [dict(effect) for effect in (draft.get("effects") or [])],
        "image_url": draft.get("image_url"),
        "value": draft.get("value"),
    }
    if draft.get("expected_version") is not None:
        payload["expected_version"] = draft["expected_version"]
    return payload


def build_item_payload(
    draft: dict[str, Any],
    *,
    expected_version: int | None = None,
    schema_version: int | None = None,
) -> dict[str, Any]:
    """Assemble the backend item mutation payload.

    Explicit ``expected_version``/``schema_version`` override the draft; when
    omitted the draft's own values (if any) are preserved.
    """
    payload = normalize_draft(draft)
    if expected_version is not None:
        payload["expected_version"] = expected_version
    if schema_version is not None:
        payload["schema_version"] = schema_version
    return payload


def effects_preview(effects: list[dict[str, Any]]) -> str:
    if not effects:
        return "No effects."
    return "\n".join(f"• {describe_effect(effect)}" for effect in effects)
