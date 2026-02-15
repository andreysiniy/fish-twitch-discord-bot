from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from domain.schemas.rpg import InventoryDTO, DropItemDTO

ALLOWED_CHANNEL_ROLES = {"editor", "moderator"}

# --- Channels ---

class ChannelCreateDTO(BaseModel):
    twitch_id: str
    name: str

class ChannelUpdateDTO(BaseModel):
    is_active: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None 

class ChannelResponseDTO(BaseModel):
    id: int
    twitch_id: str
    name: str
    is_active: bool
    config: Dict[str, Any]

    class Config:
        from_attributes = True 

# --- Rewards ---

class RewardPoolUpdateDTO(BaseModel):
    items_drop_rate: Optional[float] = Field(0.1, description="Chance to drop an item")
    location_name: Optional[str] = Field(None, description="Display name for location")
    requirements: Optional[Dict[str, Any]] = Field(
        None,
        description="Location entry requirements (level, total_fish_stat, total_mass_stat)"
    )
    rewards: List[Dict[str, Any]] = Field(..., description="Rewards data to update the pool")
    items: Optional[List[DropItemDTO]] = Field(None, description="Optional list of detailed drop items")

class RewardPoolResponseDTO(BaseModel):
    location_id: str
    location_name: str
    requirements: Dict[str, Any] = Field(default_factory=dict)
    rewards_data: List[Dict[str, Any]]
    items_drop_rate: float
    items: List[DropItemDTO]
    
    class Config:
        from_attributes = True

# --- Player Admin ---

class AdminPlayerDTO(BaseModel):
    user_twitch_id: str
    username: str
    level: int
    xp: int
    current_location_id: str
    inventory: InventoryDTO

    class Config:
        from_attributes = True 

class PlayerListResponse(BaseModel):
    total: int
    players: List[AdminPlayerDTO]


class ChannelAccessUpsertDTO(BaseModel):
    user_twitch_id: str
    user_twitch_name: str
    role: str = Field(..., description="Role for the channel user access")


class ChannelAccessResponseDTO(BaseModel):
    user_twitch_id: str
    user_twitch_name: str
    role: str

    class Config:
        from_attributes = True


class ChannelAccessListRequestDTO(BaseModel):
    actor_twitch_id: Optional[str] = None


class ChannelAccessManageRequestDTO(BaseModel):
    actor_twitch_id: Optional[str] = None
    user_twitch_id: str
    user_twitch_name: str
    role: str = Field(..., description="Role for the channel user access")


class ChannelAccessRemoveRequestDTO(BaseModel):
    actor_twitch_id: Optional[str] = None
    user_twitch_id: str
