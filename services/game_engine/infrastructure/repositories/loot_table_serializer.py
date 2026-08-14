"""Shared serialization of loot-table entries for both drop paths.

Fishing and lootbox resolution must see identical candidate shapes so a single
selector can drive both. ``remaining_stock`` is ``None`` for unlimited entries
and the current integer stock otherwise; the selector excludes ``0`` before it
computes the weighted denominator.
"""

from typing import Any

from infrastructure.models import LootTableEntry, LootTableEntryStock
from sqlalchemy.orm import Session


def load_stock_by_entry(db: Session, entries: list[LootTableEntry]) -> dict[int, int | None]:
    """Return ``{entry_id: remaining_quantity}``; unlimited entries are ``None``."""
    entry_ids = [entry.id for entry in entries]
    if not entry_ids:
        return {}
    rows = (
        db.query(LootTableEntryStock)
        .filter(LootTableEntryStock.loot_table_entry_id.in_(entry_ids))
        .all()
    )
    return {row.loot_table_entry_id: int(row.remaining_quantity) for row in rows}


def serialize_loot_table_entry(
    entry: LootTableEntry, remaining_stock: int | None = None
) -> dict[str, Any]:
    """Serialize a loot-table entry into the shared drop candidate shape."""
    definition = entry.definition
    return {
        "_source": "loot_table",
        "db_id": entry.id,
        "item_id": definition.item_id,
        "title": definition.title,
        "description": definition.description,
        "image_url": definition.image_url,
        "rarity": definition.rarity,
        "item_type": definition.type,
        "equipment_slot": definition.slot,
        "max_durability": definition.max_durability,
        "break_policy": definition.break_policy,
        "stack_size": definition.stack_size,
        "weight": entry.weight,
        "xp_gain": entry.xp_gain,
        "quantity": None,
        "min_quantity": entry.min_quantity,
        "max_quantity": entry.max_quantity,
        "message": entry.message or "You caught {name}!",
        "effects": definition.effects or [],
        "definition_version": definition.version,
        "item_definition_id": entry.item_definition_id,
        "loot_table_id": entry.loot_table_id,
        "loot_table_entry_id": entry.id,
        "remaining_stock": remaining_stock,
    }
