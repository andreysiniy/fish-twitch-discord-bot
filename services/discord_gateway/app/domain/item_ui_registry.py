"""Human-facing item UI registry (wizard spec §7/§8/§9.2).

Maps Discord item templates to backend item defaults and keeps the
template/label vocabulary in one place so the wizard screens and the review
card always agree on naming. ``template`` is UI metadata only and is never
sent to the backend item payload (spec §8/§41).
"""

import re
from typing import Any

ITEM_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,119}$")

# Template descriptors: value is the UI/Redis template key, label is what the
# admin sees, item_type/slot/stack defaults come from spec §8.
ITEM_TEMPLATES: list[dict[str, Any]] = [
    {
        "value": "fishing_rod",
        "label": "Fishing Rod",
        "item_type": "equipment",
        "default_slot": "rod",
        "default_stack": 1,
        "effects": "warning",
    },
    {
        "value": "bait",
        "label": "Bait Equipment",
        "item_type": "equipment",
        "default_slot": "bait",
        "default_stack": 1,
        "effects": "warning",
    },
    {
        "value": "defense",
        "label": "Defense Equipment",
        "item_type": "equipment",
        "default_slot": "defense",
        "default_stack": 1,
        "effects": "warning",
    },
    {
        "value": "storage",
        "label": "Storage Equipment",
        "item_type": "equipment",
        "default_slot": "storage",
        "default_stack": 1,
        "effects": "warning",
    },
    {
        "value": "charm",
        "label": "Charm",
        "item_type": "equipment",
        "default_slot": None,
        "default_stack": 1,
        "effects": "warning",
    },
    {
        "value": "consumable",
        "label": "Consumable",
        "item_type": "consumable",
        "default_slot": None,
        "default_stack": 20,
        "effects": "required",
    },
    {
        "value": "lootbox",
        "label": "Loot Box",
        "item_type": "lootbox",
        "default_slot": None,
        "default_stack": 20,
        "effects": "required",
    },
    {
        "value": "material",
        "label": "Material",
        "item_type": "material",
        "default_slot": None,
        "default_stack": 100,
        "effects": "optional",
    },
    {
        "value": "quest",
        "label": "Quest Item",
        "item_type": "quest",
        "default_slot": None,
        "default_stack": 1,
        "effects": "optional",
    },
    {
        "value": "currency",
        "label": "Currency Item",
        "item_type": "currency",
        "default_slot": None,
        "default_stack": 1000,
        "effects": "optional",
    },
    {
        "value": "collectible",
        "label": "Collectible",
        "item_type": "collectible",
        "default_slot": None,
        "default_stack": 1,
        "effects": "optional",
    },
    {
        "value": "advanced",
        "label": "Advanced Item",
        "item_type": None,
        "default_slot": None,
        "default_stack": 1,
        "effects": "depends",
    },
]

TEMPLATES_BY_VALUE: dict[str, dict[str, Any]] = {item["value"]: item for item in ITEM_TEMPLATES}

RARITY_OPTIONS = [
    ("Common", "common"),
    ("Rare", "rare"),
    ("Epic", "epic"),
    ("Legendary", "legendary"),
]

BREAK_BEHAVIOR_OPTIONS = [
    ("Indestructible", "indestructible"),
    ("Stay Broken", "retain_broken"),
    ("Unequip When Broken", "unequip_broken"),
    ("Destroy When Broken", "destroy_at_zero"),
]

CHARM_SLOT_OPTIONS = [
    ("Charm Slot 1", "charm_1"),
    ("Charm Slot 2", "charm_2"),
]

# Advanced template lets the admin pick the backend type manually (spec §8).
ITEM_TYPE_OPTIONS = [
    ("Equipment", "equipment"),
    ("Consumable", "consumable"),
    ("Loot Box", "lootbox"),
    ("Material", "material"),
    ("Quest Item", "quest"),
    ("Currency Item", "currency"),
    ("Collectible", "collectible"),
]

EQUIPMENT_SLOT_LABELS = {
    "rod": "Fishing Rod",
    "bait": "Bait",
    "defense": "Defense",
    "storage": "Storage",
    "charm_1": "Charm Slot 1",
    "charm_2": "Charm Slot 2",
}


def template_to_defaults(template: str) -> dict[str, Any]:
    """Translate a UI template into backend item defaults (spec §8).

    ``item_type`` is left as the template default except for the advanced
    template, where the admin picks it during the mechanics step.
    """
    spec = TEMPLATES_BY_VALUE[template]
    defaults: dict[str, Any] = {
        "item_type": spec["item_type"] or "material",
        "stack_size": int(spec["default_stack"]),
        "break_policy": "indestructible",
        "max_durability": None,
    }
    if spec["item_type"] == "equipment":
        defaults["equipment_slot"] = spec["default_slot"]
        defaults["stack_size"] = 1
    else:
        defaults["equipment_slot"] = None
    return defaults


def template_for_item_type(item_type: str, equipment_slot: str | None = None) -> str | None:
    """Derive the UI template key from backend item data (wizard spec §54).

    The template is UI metadata only (never part of the backend payload). Editing
    a ``fishing_rod``-style item must re-use the same template so the mechanics
    view and review label agree with the create flow.
    """
    if item_type == "equipment":
        if equipment_slot in ("charm_1", "charm_2"):
            return "charm"
        slot_map = {
            "rod": "fishing_rod",
            "bait": "bait",
            "defense": "defense",
            "storage": "storage",
        }
        return slot_map.get(equipment_slot, "fishing_rod")
    return item_type if item_type in TEMPLATES_BY_VALUE else None


def validate_item_id(item_id: str) -> bool:
    return bool(ITEM_ID_PATTERN.fullmatch(item_id.strip().lower()))


def slugify_item_id(display_name: str) -> str | None:
    """Build a stable item ID from a display name (spec §9.2).

    ``Storm Rod`` → ``storm_rod``. Returns ``None`` when a valid ID cannot be
    derived automatically so the wizard asks the admin for a manual ID.
    """
    slug = display_name.strip().lower()
    slug = re.sub(r"[^a-z0-9_-]+", "_", slug)
    slug = slug.strip("_")
    if not ITEM_ID_PATTERN.fullmatch(slug):
        return None
    return slug
