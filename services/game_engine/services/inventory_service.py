from infrastructure.repositories.user_repo import UserRepository
from domain.schemas.rpg import EquipRequestDTO, EquipResponseDTO, InventoryResponseDTO
from sqlalchemy.orm.attributes import flag_modified
from domain.logic.inventory_utils import find_equipped_rod

class InventoryService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    def equip_item(self, data: EquipRequestDTO) -> EquipResponseDTO:
        user = self.user_repo.get_progress(data.user_id, data.channel_id)
        if not user:
            return EquipResponseDTO(success=False, message="Try fishing first! You have no inventory.")
        inventory = dict(user.inventory) 
        items = inventory.get("items", [])
        
        target_item = next((item for item in items if item.get("slot_id") == data.slot_id), None)

        if not target_item:
            return EquipResponseDTO(success=False, message=f"Slot {data.slot_id} is empty! Check your inventory (!fishbag).")

        if target_item.get("type") != "rod":
             return EquipResponseDTO(success=False, message=f"{target_item.get('name')} — is not a rod!")

        inventory["equipped_rod_slot"] = target_item.get("slot_id")
        
        user.inventory = inventory
        flag_modified(user, "inventory")
        self.user_repo.save_progress(user)

        return EquipResponseDTO(
            success=True, 
            message=f"Equipped [{target_item['slot_id']}] {target_item['name']}.",
            equipped_item_name=target_item['name']
        )
    
    def get_inventory_msg(self, user_id: str, channel_id: str) -> InventoryResponseDTO:
        user = self.user_repo.get_progress(user_id, channel_id)
        if not user:
            return InventoryResponseDTO(success=False, message="You have no inventory.", items=[])
        
        inventory_data = dict(user.inventory)  
        items = inventory_data.get("items", [])
        equipped_rod = find_equipped_rod(inventory_data)
        equipped_rod_slot = equipped_rod.get("slot_id") if equipped_rod else None

        message = f"Inventory: {len(items)} items."
        if equipped_rod:
            message += f" Equipped rod: [{equipped_rod_slot}] {equipped_rod.get('name')}."
        
        for item in items:
            message += f"\n[{item.get('slot_id')}] {item.get('name')} x{item.get('quantity', 1)}"

        return InventoryResponseDTO(
            success=True,
            message=message,
            items=items,
            equipped_rod_slot=equipped_rod_slot,
            max_slots=inventory_data.get("max_slots", 20)
        )
