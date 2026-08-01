from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from domain.schemas.common import Rarity

class ItemStats(BaseModel):
    luck_bonus: float = 0.0
    points_bonus: int = 0
    resist_bonus: float = 0.0
    xp_bonus_pct: float = 0.0
    durability: int = 100
    can_break: bool = False

class BaseItemDTO(BaseModel):
    item_id: str
    title: str
    description: str | None = None
    rarity: Rarity = Rarity.COMMON
    type: str = "fish"
    slot: str | None = None
    durability: int | None = None
    stack_size: int = 1
    image_url: str | None = None
    base_stats: Dict[str, Any] = Field(default_factory=dict)


class DropItemDTO(BaseItemDTO):
    weight: int = 100
    xp_gain: int = 0
    quantity: Optional[int] = None
    message: str | None = None
    
class InventoryItemDTO(BaseItemDTO):
    quantity: int = 1
    slot_id: int 
    current_durability: int | None = None
    obtained_at: str | None = None


class InventoryDTO(BaseModel):
    items: List[InventoryItemDTO] = Field(default_factory=list)
    equipped_rod_slot: Optional[int] = None
    max_slots: int = 20

class InventoryResponseDTO(InventoryDTO):
    success: bool
    message: str | None = None

class EquipRequestDTO(BaseModel):
    user_id: str
    channel_id: str
    slot_id: int | None = None

class EquipResponseDTO(BaseModel):
    success: bool
    message: str
    equipped_item_name: str | None = None

class PlayerStateDTO(BaseModel):
    twitch_id: str
    username: str
    level: int
    current_xp: int
    xp_to_next_level: int
    total_fish_stat: int
    total_mass_stat: float
    current_mass: float
    current_location_id: str
    inventory: InventoryDTO
