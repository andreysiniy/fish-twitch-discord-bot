from pydantic import BaseModel, Field
from typing import List, Optional
from domain.schemas.common import Rarity

class ItemStats(BaseModel):
    """Характеристики предмета"""
    luck_bonus: float = 0.0      # +0.1 к удаче
    points_bonus: int = 0        # +10 к очкам
    xp_bonus_pct: float = 0.0    # +5% к опыту
    durability: int = 100        # Прочность
    can_break: bool = False      # Может ли сломаться

class ItemDTO(BaseModel):
    """Предмет в игре"""
    id: str
    name: str
    description: str | None = None
    rarity: Rarity = Rarity.COMMON
    type: str = "fish"           # fish, rod, bait
    stats: ItemStats = Field(default_factory=ItemStats)

class InventoryDTO(BaseModel):
    """Структура инвентаря игрока"""
    items: List[ItemDTO] = []
    equipped_rod_id: Optional[str] = None
    max_slots: int = 20

class PlayerStateDTO(BaseModel):
    """Полное состояние игрока (Профиль)"""
    twitch_id: str
    username: str
    level: int
    current_xp: int
    xp_to_next_level: int
    current_location_id: str
    inventory: InventoryDTO