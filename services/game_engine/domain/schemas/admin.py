from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.game_limits import (
    MAX_COOLDOWN_SECONDS,
    MAX_EVENT_DURATION_SECONDS,
    MIN_COOLDOWN_SECONDS,
    MIN_EVENT_DURATION_SECONDS,
)
from domain.config_schema import EventModifiers, LocationRequirements, RewardDefinition
from domain.item_schema import ItemDefinitionData
from domain.schemas.rpg import InventoryDTO, InventoryItemDTO

ALLOWED_CHANNEL_ROLES = {"editor", "moderator"}

# --- Channels ---

class ChannelCreateDTO(BaseModel):
    twitch_id: str
    name: str

class ChannelUpdateDTO(BaseModel):
    is_active: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None
    se_token: Optional[str] = None
    se_channel_id: Optional[str] = None

class ChannelResponseDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    twitch_id: str
    name: str
    is_active: bool
    config: Dict[str, Any]
    se_channel_id: Optional[str] = None



class StreamElementsIntegrationUpsertDTO(BaseModel):
    se_token: str = Field(..., min_length=1)


class StreamElementsIntegrationResponseDTO(BaseModel):
    status: str
    se_channel_id: str

# --- Rewards ---

class LocationItemResponseDTO(BaseModel):
    item_id: str
    weight: int = 100
    xp_gain: int = 0
    quantity: Optional[int] = None
    message: Optional[str] = None
    db_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    rarity: str = "common"
    item_type: str = "collectible"
    equipment_slot: str | None = None
    max_durability: int | None = None
    break_policy: str = "indestructible"
    stack_size: int = 1
    image_url: Optional[str] = None
    effects: List[Dict[str, Any]] = Field(default_factory=list)
    definition_version: int = 1


class RewardPoolUpdateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items_drop_rate: Optional[float] = Field(0.1, ge=0, le=1, description="Chance to drop an item")
    location_name: Optional[str] = Field(None, description="Display name for location")
    requirements: Optional[LocationRequirements] = Field(
        None,
        description="Location entry requirements (level, total_fish_stat, total_mass_stat)",
    )
    rewards: List[RewardDefinition] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Rewards data to update the pool",
    )
class RewardPoolResponseDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    location_id: str
    location_name: str
    requirements: Dict[str, Any] = Field(default_factory=dict)
    rewards_data: List[Dict[str, Any]]
    items_drop_rate: float
    items: List[LocationItemResponseDTO]


# --- Player Admin ---

class AdminPlayerDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_twitch_id: str
    username: str
    level: int
    xp: int
    current_location_id: str
    inventory: InventoryDTO


class PlayerListResponse(BaseModel):
    total: int
    players: List[AdminPlayerDTO]


class ChannelAccessUpsertDTO(BaseModel):
    user_twitch_id: str
    user_twitch_name: str
    role: str = Field(..., description="Role for the channel user access")


class ChannelAccessResponseDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_twitch_id: str
    user_twitch_name: str
    role: str



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
    seconds: int = Field(..., ge=MIN_COOLDOWN_SECONDS, le=MAX_COOLDOWN_SECONDS)
    scope: Optional[str] = None


class FishCooldownSetResponseDTO(BaseModel):
    chat_message: str
    fishing_cooldown: int
    subs_fishing_cooldown: int
    updated_scope: str


class ItemDefinitionCreateDTO(ItemDefinitionData):
    expected_version: int | None = Field(None, ge=1)


class ItemDefinitionResponseDTO(ItemDefinitionData):
    channel_twitch_id: str
    version: int
    is_active: bool
    archived_at: datetime | None = None
    updated_at: datetime


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


class FishingEventResponseDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_title: str
    is_active: bool
    modifiers: Dict[str, Any] = Field(default_factory=dict)
    override_loot_pool: Optional[str] = None



class FishingEventListRequestDTO(BaseModel):
    actor_twitch_id: Optional[str] = None


class FishingEventCreateRequestDTO(BaseModel):
    actor_twitch_id: Optional[str] = None
    event_title: str = Field(..., min_length=1, max_length=120)
    modifiers: EventModifiers = Field(default_factory=EventModifiers)
    override_loot_pool: Optional[str] = None
    is_active: bool = False


class FishingEventUpdateRequestDTO(BaseModel):
    actor_twitch_id: Optional[str] = None
    event_title: Optional[str] = Field(None, min_length=1, max_length=120)
    modifiers: Optional[EventModifiers] = None
    override_loot_pool: Optional[str] = None
    clear_override_loot_pool: bool = False
    is_active: Optional[bool] = None


class FishingEventDeleteRequestDTO(BaseModel):
    actor_twitch_id: Optional[str] = None


class FishingEventToggleRequestDTO(BaseModel):
    actor_twitch_id: Optional[str] = None
    event_number: int = Field(..., ge=1)
    duration_seconds: Optional[int] = Field(
        None,
        ge=MIN_EVENT_DURATION_SECONDS,
        le=MAX_EVENT_DURATION_SECONDS,
    )


class FishingEventToggleResponseDTO(BaseModel):
    status: str
    chat_message: str
    event: Optional[FishingEventResponseDTO] = None
    active_event_id: Optional[int] = None
    scheduled_disable_at: Optional[int] = None
    scheduler_job: Optional[Dict[str, Any]] = None


class FishingEventListResponseDTO(BaseModel):
    chat_message: str
    active_event_id: Optional[int] = None
    items: List[FishingEventResponseDTO] = Field(default_factory=list)
