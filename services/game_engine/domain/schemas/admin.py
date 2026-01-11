from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from domain.schemas.rpg import InventoryDTO

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
    rewards: List[Dict[str, Any]] = Field(..., description="Rewards data to update the pool")

class RewardPoolResponseDTO(BaseModel):
    location_id: str
    rewards_data: List[Dict[str, Any]]

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