
from pydantic import BaseModel
from typing import List, Optional
from domain.schemas.actions import GameAction
from domain.schemas.rpg import DropItemDTO

class FishRequest(BaseModel):
    user_id: str
    username: str
    channel_id: str
    user_input: Optional[str] = None  # Например !fish <bet>
    is_mod: bool = False
    is_sub: bool = False

class LevelUpInfo(BaseModel):
    old_level: int
    new_level: int
    rewards: List[str] = [] 

class FishResponse(BaseModel):
    chat_message: str
    
    xp_gained: int
    money_change: int = 0
    
    item_drop: Optional[DropItemDTO] = None
    
    level_up: Optional[LevelUpInfo] = None
    
    actions: List[GameAction] = []