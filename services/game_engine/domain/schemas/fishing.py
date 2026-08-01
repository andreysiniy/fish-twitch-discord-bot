
from pydantic import BaseModel, Field
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


class FishCooldownRequest(BaseModel):
    channel_id: str
    user_id: Optional[str] = None
    username: Optional[str] = None
    is_mod: bool = False
    is_sub: bool = False


class FishCooldownResponse(BaseModel):
    success: bool
    chat_message: str
    cooldown_time: int
    cooldown_left: int


class FishTravelRequest(BaseModel):
    user_id: str
    username: str
    channel_id: str
    user_input: Optional[str] = None
    location_number: Optional[int] = None

class LocationRequirementDTO(BaseModel):
    level: int = 0
    total_fish_stat: int = 0
    total_mass_stat: float = 0.0

class TravelLocationDTO(BaseModel):
    number: int
    location_id: str
    location_name: str
    is_current: bool
    is_available: bool
    requirements: LocationRequirementDTO
    missing_requirements: List[str] = Field(default_factory=list)

class FishTravelResponse(BaseModel):
    success: bool
    chat_message: str
    current_location_id: str
    selected_location_id: Optional[str] = None
    locations: List[TravelLocationDTO] = Field(default_factory=list)

class LevelUpInfo(BaseModel):
    old_level: int
    new_level: int
    rewards: List[str] = Field(default_factory=list)

class FishResponse(BaseModel):
    chat_message: str
    
    xp_gained: int
    
    item_drop: Optional[DropItemDTO] = None
    
    level_up: Optional[LevelUpInfo] = None
    
    actions: List[GameAction] = Field(default_factory=list)

class RobberyResultDTO(BaseModel):
    is_success: bool
    amount_stolen: float
    victim_name: str
    victim_twitch_id: str
    victim_new_mass: float
    chance_used: float    

class RussianRouletteResultDTO(BaseModel):
    is_hit: bool
    bullets: int
    chambers: int
    message: str
    mass_delta: float = 0.0
    penalty: Optional[Dict[str, Any]] = None
    reward: Optional[Dict[str, Any]] = None

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
    roulette_result: Optional[RussianRouletteResultDTO] = None


class PlayerStatsDTO(BaseModel):
    level: int = 1
    xp: int = 0
    xp_to_next_level: int = 0
    current_mass: float = 0.0
    total_fish_stat: int = 0
    rod_name: str
    luck_bonus: float = 0.0
    resist_bonus: float = 0.0
    xp_bonus_pct: float = 0.0
    rank: int = 0
    total_mass_stat: float = 0.0


class FishStatsResponse(BaseModel):
    success: bool
    chat_message: str
    stats: PlayerStatsDTO


class TopPlayerDTO(BaseModel):
    rank: int
    user_twitch_id: str
    username: str
    level: int = 1
    xp: int = 0
    current_mass: float = 0.0
    total_fish_stat: int = 0
    total_mass_stat: float


class FishTopResponse(BaseModel):
    success: bool
    chat_message: str
    mode: str = "current"
    top: List[TopPlayerDTO] = Field(default_factory=list)
