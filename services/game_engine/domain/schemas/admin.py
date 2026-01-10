from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

# --- Channels ---

class ChannelCreateDTO(BaseModel):
    twitch_id: str
    name: str

class ChannelUpdateDTO(BaseModel):
    is_active: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None # Префикс, язык и т.д.

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