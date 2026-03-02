def _to_inventory_dict(item_obj) -> dict:
    definition = getattr(item_obj, "definition", None)
    logical_item_id = getattr(definition, "item_id", None) or getattr(item_obj, "item_id", "")
    title = getattr(definition, "title", None) or logical_item_id or "Unknown"
    stats = getattr(definition, "base_stats", {}) or {}

    return {
        "slot_id": getattr(item_obj, "slot_id", None),
        "item_id": logical_item_id,
        "title": title,
        "description": getattr(definition, "description", None),
        "image_url": getattr(definition, "image_url", None),
        "type": getattr(definition, "type", "equipment"),
        "slot": getattr(definition, "slot", None),
        "rarity": getattr(definition, "rarity", "common"),
        "durability": getattr(definition, "durability", None),
        "stack_size": getattr(definition, "stack_size", 1),
        "quantity": getattr(item_obj, "quantity", 1),
        "current_durability": getattr(item_obj, "current_durability", None),
        "base_stats": stats,
        "meta": getattr(item_obj, "meta", {}) or {},
    }


def find_equipped_rod(inventory: dict, inventory_items: list | None = None) -> dict | None:
    slot_id = (inventory or {}).get("equipped_rod_slot")
    if slot_id is None:
        return None

    if inventory_items is not None:
        for item in inventory_items:
            if getattr(item, "slot_id", None) == slot_id:
                return _to_inventory_dict(item)
        return None

    items = (inventory or {}).get("items", [])
    return next((i for i in items if i.get("slot_id") == slot_id), None)
