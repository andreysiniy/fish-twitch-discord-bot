from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from domain.schemas.common import Rarity

class ItemStats(BaseModel):
    """Характеристики предмета"""
    luck_bonus: float = 0.0      # +0.1 к удаче
    points_bonus: int = 0        # +10 к очкам
    xp_bonus_pct: float = 0.0    # +5% к опыту
    durability: int = 100        # Прочность
    can_break: bool = False      # Может ли сломаться

class BaseItemDTO(BaseModel):
    """Общие поля для предмета (и в базе, и в инвентаре)"""
    item_id: str
    name: str
    description: str | None = None
    rarity: Rarity = Rarity.COMMON
    type: str = "fish"
    image_url: str | None = None
    stats: Dict[str, Any] = Field(default_factory=dict)

class DropItemDTO(BaseItemDTO):
    """Предмет как часть таблицы дропа (настройки)"""
    weight: int = 100
    xp_gain: int = 0
    quantity: Optional[int] = None
    message: str | None = None
    
class InventoryItemDTO(BaseItemDTO):
    """Предмет в инвентаре игрока"""
    quantity: int = 1
    slot_id: int 
    current_durability: int | None = None
    obtained_at: str | None = None


class InventoryDTO(BaseModel):
    """Структура инвентаря игрока"""
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
    """Полное состояние игрока (Профиль)"""
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
