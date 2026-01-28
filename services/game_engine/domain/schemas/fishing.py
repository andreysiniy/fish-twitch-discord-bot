
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
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
    
    item_drop: Optional[DropItemDTO] = None
    
    level_up: Optional[LevelUpInfo] = None
    
    actions: List[GameAction] = []

class RobberyResultDTO(BaseModel):
    is_success: bool
    amount_stolen: float
    victim_name: str
    victim_twitch_id: str
    victim_new_mass: float
    chance_used: float    

class FishingResult(BaseModel):
    loot: Dict[str, Any]
    item_drop: Optional[Dict]
    username: str
    xp_gained: int
    mass_gained: float
    is_level_up: bool
    new_level: int
    luck_used: float
    durability_loss: int = 1
    robbery_result: Optional[RobberyResultDTO] = None