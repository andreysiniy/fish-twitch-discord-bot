from domain.schemas.rpg import (
    EquipRequestDTO,
    EquipResponseDTO,
    InventoryResponseDTO,
    UnequipRequestDTO,
    UseItemRequestDTO,
    UseItemResponseDTO,
)
from infrastructure.repositories.inventory_repo import InventoryRepository
from infrastructure.repositories.user_repo import UserRepository
from services.player_modifier_service import PlayerModifierService


class InventoryService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo
        self.inventory_repo = InventoryRepository(user_repo.db)
        self.modifier_service = PlayerModifierService(user_repo.db)

    def equip_item(self, data: EquipRequestDTO) -> EquipResponseDTO:
        user = self.user_repo.get_progress(data.user_id, data.channel_id)
        if not user:
            return EquipResponseDTO(success=False, message="You have no inventory.")
        try:
            equipped = self.inventory_repo.equip(
                user.id,
                data.slot_id,
                data.equipment_slot.value if data.equipment_slot else None,
            )
        except ValueError as error:
            return EquipResponseDTO(success=False, message=str(error))
        title = equipped.inventory_item.definition.title
        return EquipResponseDTO(
            success=True,
            message=f"Equipped [{data.slot_id}] {title} in {equipped.slot}.",
            equipped_item_name=title,
        )

    def unequip_item(self, data: UnequipRequestDTO) -> EquipResponseDTO:
        user = self.user_repo.get_progress(data.user_id, data.channel_id)
        if not user:
            return EquipResponseDTO(success=False, message="You have no inventory.")
        self.inventory_repo.unequip(user.id, data.equipment_slot.value)
        return EquipResponseDTO(
            success=True,
            message=f"Unequipped {data.equipment_slot.value}.",
        )

    def use_item(self, data: UseItemRequestDTO) -> UseItemResponseDTO:
        user = self.user_repo.get_progress(data.user_id, data.channel_id)
        if not user:
            raise ValueError("You have no inventory")
        return UseItemResponseDTO.model_validate(
            self._inventory_repository(user).use_item(
                user, data.slot_id, data.idempotency_key
            )
        )

    def get_inventory_msg(self, user_id: str, channel_id: str) -> InventoryResponseDTO:
        user = self.user_repo.get_progress(user_id, channel_id)
        if not user:
            return InventoryResponseDTO(success=False, message="You have no inventory.", items=[])

        db_items = self.user_repo.get_user_inventory_items(user.id)
        equipped = self.inventory_repo.get_equipped(user.id)
        equipped_slots = {
            row.slot: row.inventory_item.slot_id
            for row in equipped
            if row.inventory_item is not None
        }
        items = [self._to_inventory_dto(item) for item in db_items]

        message = f"Inventory: {len(items)} occupied slots."
        if equipped_slots:
            equipment_text = ", ".join(
                f"{slot}=[{inventory_slot}]"
                for slot, inventory_slot in sorted(equipped_slots.items())
            )
            message += f" Equipped: {equipment_text}."
        for item in items:
            durability = (
                f" durability {item['current_durability']}/{item['max_durability']}"
                if item["max_durability"] is not None
                else ""
            )
            message += (
                f"\n[{item['slot_id']}] {item['title']} x{item['quantity']}"
                f" ({item['item_type']}, {item['rarity']}){durability}"
            )

        return InventoryResponseDTO(
            success=True,
            message=message,
            items=items,
            equipped_slots=equipped_slots,
            equipped_rod_slot=equipped_slots.get("rod"),
            max_slots=max(
                int(getattr(user, "base_inventory_slots", 20) or 20)
                + self.modifier_service.inventory_slot_bonus(user),
                1,
            ),
        )

    def _inventory_repository(self, user) -> InventoryRepository:
        return InventoryRepository(
            self.user_repo.db,
            max_slots_add=self.modifier_service.inventory_slot_bonus(user),
        )

    @staticmethod
    def _display_title(definition, fallback_item_id: str) -> str:
        if definition and getattr(definition, "title", None):
            return str(definition.title)
        if definition and getattr(definition, "item_id", None):
            return str(definition.item_id)
        return fallback_item_id

    def _to_inventory_dto(self, item) -> dict:
        definition = item.definition
        if not definition:
            raise ValueError(f"Inventory item {item.id} has no definition")
        meta = item.meta or {}
        return {
            "id": item.id,
            "item_id": definition.item_id,
            "title": self._display_title(definition, definition.item_id),
            "description": definition.description,
            "rarity": definition.rarity,
            "item_type": definition.type,
            "equipment_slot": definition.slot,
            "max_durability": definition.max_durability,
            "break_policy": definition.break_policy,
            "stack_size": definition.stack_size,
            "image_url": definition.image_url,
            "effects": definition.effects or [],
            "definition_version": item.definition_version,
            "quantity": item.quantity,
            "slot_id": item.slot_id,
            "current_durability": item.current_durability,
            "obtained_at": meta.get("obtained_at"),
            "version": item.version,
            "meta": meta,
        }
