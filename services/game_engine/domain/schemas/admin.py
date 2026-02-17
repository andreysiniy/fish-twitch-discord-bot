from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from domain.schemas.rpg import InventoryDTO, InventoryItemDTO

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

class LocationItemUpdateDTO(BaseModel):
    item_id: str
    weight: int = 100
    xp_gain: int = 0
    quantity: Optional[int] = None
    message: Optional[str] = None


class RewardPoolUpdateDTO(BaseModel):
    items_drop_rate: Optional[float] = Field(0.1, description="Chance to drop an item")
    location_name: Optional[str] = Field(None, description="Display name for location")
    requirements: Optional[Dict[str, Any]] = Field(
        None,
        description="Location entry requirements (level, total_fish_stat, total_mass_stat)"
    )
    rewards: List[Dict[str, Any]] = Field(..., description="Rewards data to update the pool")
    items: Optional[List[LocationItemUpdateDTO]] = Field(
        None,
        description="Optional list of location drop items"
    )

class RewardPoolResponseDTO(BaseModel):
    location_id: str
    location_name: str
    requirements: Dict[str, Any] = Field(default_factory=dict)
    rewards_data: List[Dict[str, Any]]
    items_drop_rate: float
    items: List[LocationItemUpdateDTO]
    
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


class FishCooldownSetRequestDTO(BaseModel):
    actor_twitch_id: Optional[str] = None
    seconds: int = Field(..., ge=0)
    scope: Optional[str] = None


class FishCooldownSetResponseDTO(BaseModel):
    chat_message: str
    fishing_cooldown: int
    subs_fishing_cooldown: int
    updated_scope: str


class ItemDefinitionCreateDTO(BaseModel):
    item_id: str
    name: str
    description: Optional[str] = None
    type: str = "fish"
    rarity: str = "common"
    image_url: Optional[str] = None
    base_stats: Dict[str, Any] = Field(default_factory=dict)
    is_sellable: bool = True
    is_tradeable: bool = True


class ItemDefinitionResponseDTO(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    type: str
    rarity: str
    image_url: Optional[str] = None
    base_stats: Dict[str, Any] = Field(default_factory=dict)
    is_sellable: bool
    is_tradeable: bool

    class Config:
        from_attributes = True


class GrantItemRequestDTO(BaseModel):
    channel_twitch_id: str
    user_twitch_id: str
    item_id: str
    quantity: int = 1
    slot_id: Optional[int] = None
    current_durability: Optional[int] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class GrantItemResponseDTO(BaseModel):
    success: bool
    message: str
    item: InventoryItemDTO
