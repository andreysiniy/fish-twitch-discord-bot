def _to_inventory_dict(item_obj) -> dict:
    definition = getattr(item_obj, "definition", None)
    logical_item_id = getattr(definition, "item_id", None) or getattr(item_obj, "item_id", "")
    title = getattr(definition, "title", None) or logical_item_id or "Unknown"
    return {
        "slot_id": getattr(item_obj, "slot_id", None),
        "item_id": logical_item_id,
        "title": title,
        "description": getattr(definition, "description", None),
        "image_url": getattr(definition, "image_url", None),
        "item_type": getattr(definition, "type", "collectible"),
        "equipment_slot": getattr(definition, "slot", None),
        "rarity": getattr(definition, "rarity", "common"),
        "max_durability": getattr(definition, "max_durability", None),
        "break_policy": getattr(definition, "break_policy", "indestructible"),
        "stack_size": getattr(definition, "stack_size", 1),
        "quantity": getattr(item_obj, "quantity", 1),
        "current_durability": getattr(item_obj, "current_durability", None),
        "effects": getattr(definition, "effects", []) or [],
        "meta": getattr(item_obj, "meta", {}) or {},
    }


def find_equipped_rod(equipped_items: list | None = None, inventory_items: list | None = None) -> dict | None:
    """Return the currently equipped rod, reading from the normalized table.

    ``equipped_items`` is a list of ``EquippedItem`` rows; each exposes ``slot``
    and an ``inventory_item`` (the concrete ``InventoryItem``). This is the single
    source of truth — the legacy ``UserProgress.inventory`` JSON is not consulted.
    """
    equipped_items = list(equipped_items or [])
    for equipped in equipped_items:
        if getattr(equipped, "slot", None) != "rod":
            continue
        item = getattr(equipped, "inventory_item", None)
        if item is not None:
            return _to_inventory_dict(item)
        # Fallback: match the equipped inventory item by id if items provided.
        inventory_item_id = getattr(equipped, "inventory_item_id", None)
        if inventory_items is not None and inventory_item_id is not None:
            for candidate in inventory_items:
                if getattr(candidate, "id", None) == inventory_item_id:
                    return _to_inventory_dict(candidate)
        return None
    return None
