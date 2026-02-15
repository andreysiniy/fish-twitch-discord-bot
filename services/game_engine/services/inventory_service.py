from sqlalchemy.orm.attributes import flag_modified

from domain.logic.inventory_utils import find_equipped_rod
from domain.schemas.rpg import EquipRequestDTO, EquipResponseDTO, InventoryResponseDTO
from infrastructure.repositories.user_repo import UserRepository


class InventoryService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    def equip_item(self, data: EquipRequestDTO) -> EquipResponseDTO:
        user = self.user_repo.get_progress(data.user_id, data.channel_id)
        if not user:
            return EquipResponseDTO(success=False, message="Try fishing first! You have no inventory.")

        inventory = dict(user.inventory or {})
        db_items = self.user_repo.get_user_inventory_items(user.id)
        target_item = next((item for item in db_items if item.slot_id == data.slot_id), None)

        if not target_item:
            return EquipResponseDTO(success=False, message=f"Slot {data.slot_id} is empty! Check your inventory (!fishbag).")

        definition = target_item.definition
        if not definition or definition.type != "rod":
            item_name = definition.name if definition else target_item.item_id
            return EquipResponseDTO(success=False, message=f"{item_name} is not a rod!")

        inventory["equipped_rod_slot"] = target_item.slot_id
        user.inventory = inventory
        flag_modified(user, "inventory")
        self.user_repo.save_progress(user)

        return EquipResponseDTO(
            success=True,
            message=f"Equipped [{target_item.slot_id}] {definition.name}.",
            equipped_item_name=definition.name
        )

    def get_inventory_msg(self, user_id: str, channel_id: str) -> InventoryResponseDTO:
        user = self.user_repo.get_progress(user_id, channel_id)
        if not user:
            return InventoryResponseDTO(success=False, message="You have no inventory.", items=[])

        inventory_data = dict(user.inventory or {})
        db_items = self.user_repo.get_user_inventory_items(user.id)
        items = [self._to_inventory_dto(item) for item in db_items]
        equipped_rod = find_equipped_rod(inventory_data, db_items)
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

    def _to_inventory_dto(self, item) -> dict:
        definition = item.definition
        meta = item.meta or {}
        return {
            "item_id": item.item_id,
            "name": definition.name if definition else item.item_id,
            "description": definition.description if definition else None,
            "rarity": definition.rarity if definition else "common",
            "type": definition.type if definition else "fish",
            "image_url": definition.image_url if definition else None,
            "stats": definition.base_stats if definition else {},
            "quantity": item.quantity,
            "slot_id": item.slot_id,
            "current_durability": item.current_durability,
            "obtained_at": meta.get("obtained_at")
        }
