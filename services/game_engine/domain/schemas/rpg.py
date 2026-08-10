from decimal import Decimal
from typing import Any, Dict, List, Optional

from domain.item_schema import BreakPolicy, EquipmentSlot, ItemEffect, ItemType
from domain.schemas.common import Rarity
from pydantic import BaseModel, ConfigDict, Field


class BaseItemDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    title: str
    description: str | None = None
    rarity: Rarity = Rarity.COMMON
    item_type: ItemType
    equipment_slot: EquipmentSlot | None = None
    max_durability: int | None = None
    max_charges: int | None = None
    break_policy: BreakPolicy = BreakPolicy.INDESTRUCTIBLE
    stack_size: int = 1
    image_url: str | None = None
    effects: List[ItemEffect] = Field(default_factory=list)
    definition_version: int = 1


class DropItemDTO(BaseItemDTO):
    weight: int = 100
    xp_gain: int = 0
    quantity: Optional[int] = None
    message: str | None = None


class InventoryItemDTO(BaseItemDTO):
    id: int
    quantity: int = 1
    slot_id: int
    current_durability: int | None = None
    current_charges: int | None = None
    obtained_at: str | None = None
    version: int = 1
    meta: Dict[str, Any] = Field(default_factory=dict)


class InventoryDTO(BaseModel):
    items: List[InventoryItemDTO] = Field(default_factory=list)
    equipped_slots: Dict[str, int] = Field(default_factory=dict)
    equipped_rod_slot: Optional[int] = None
    max_slots: int = 20


class InventoryResponseDTO(InventoryDTO):
    success: bool
    message: str | None = None


class EquipRequestDTO(BaseModel):
    user_id: str
    channel_id: str
    slot_id: int | None = Field(None)
    equipment_slot: EquipmentSlot | None = None


class EquipResponseDTO(BaseModel):
    success: bool
    message: str
    equipped_item_name: str | None = None


class UnequipRequestDTO(BaseModel):
    user_id: str
    channel_id: str
    equipment_slot: EquipmentSlot


class UseItemRequestDTO(BaseModel):
    user_id: str
    channel_id: str
    slot_id: int = Field(..., ge=1)
    idempotency_key: str = Field(..., min_length=1, max_length=200)


class UseItemResponseDTO(BaseModel):
    success: bool
    item_id: str
    item_title: str
    mass_delta: Decimal
    granted_items: List[Dict[str, Any]] = Field(default_factory=list)
    loot_resolutions: List[Dict[str, Any]] = Field(default_factory=list)
    actions: List[Dict[str, Any]] = Field(default_factory=list)


class PlayerStateDTO(BaseModel):
    twitch_id: str
    username: str
    level: int
    current_xp: int
    xp_to_next_level: int
    total_fish_stat: int
    total_mass_stat: Decimal
    current_mass: Decimal
    current_location_id: str
    inventory: InventoryDTO
