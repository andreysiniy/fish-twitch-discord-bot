def _to_inventory_dict(item_obj) -> dict:
    definition = getattr(item_obj, "definition", None)
    return {
        "slot_id": getattr(item_obj, "slot_id", None),
        "item_id": getattr(item_obj, "item_id", ""),
        "name": getattr(definition, "name", getattr(item_obj, "item_id", "Unknown")),
        "description": getattr(definition, "description", None),
        "image_url": getattr(definition, "image_url", None),
        "type": getattr(definition, "type", "fish"),
        "rarity": getattr(definition, "rarity", "common"),
        "quantity": getattr(item_obj, "quantity", 1),
        "current_durability": getattr(item_obj, "current_durability", None),
        "stats": getattr(definition, "base_stats", {}) or {},
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
