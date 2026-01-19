
def find_equipped_rod(inventory: dict) -> dict | None:
    slot_id = inventory.get("equipped_rod_slot")
    if slot_id is None:
        return None
    
    items = inventory.get("items", [])
    return next((i for i in items if i.get("slot_id") == slot_id), None)