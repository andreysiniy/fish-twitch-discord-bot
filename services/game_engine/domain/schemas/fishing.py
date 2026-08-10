from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from domain.schemas.actions import GameAction
from domain.schemas.rpg import DropItemDTO
from domain.logic.loot_selection import ItemDropResolution
from pydantic import BaseModel, Field


class FishRequest(BaseModel):
    user_id: str
    username: str
    channel_id: str
    user_input: Optional[str] = None  # e.g. !fish <bet>
    is_mod: bool = False
    is_sub: bool = False
    bypass_cooldown: bool = False
    source: Optional[str] = "twitch"
    source_request_id: Optional[str] = None
    requested_at: Optional[datetime] = None


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
    total_mass_stat: Decimal = Decimal("0.00")


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

    cast_id: Optional[str] = None
    is_replayed: bool = False


class RobberyResultDTO(BaseModel):
    is_success: bool
    victim_found: bool = True
    amount_stolen: Decimal
    victim_name: str
    victim_twitch_id: str
    victim_new_mass: Decimal
    chance_used: float
    absorbed: bool = False
    counter_actions: List[Dict[str, Any]] = Field(default_factory=list)
    roll: Decimal | None = None


class RussianRouletteResultDTO(BaseModel):
    is_hit: bool
    bullets: int
    chambers: int
    roll: Decimal | None = None
    message: str
    mass_delta: Decimal = Decimal("0.00")
    penalty: Optional[Dict[str, Any]] = None
    reward: Optional[Dict[str, Any]] = None


class FishingResult(BaseModel):
    loot: Dict[str, Any]
    item_drop: Optional[Dict]
    # Keep the canonical typed selection alongside the presentation mapping.
    # Delivery updates this object, and the cast ledger serializes it directly
    # instead of reconstructing probabilities from chat-facing fields.
    item_drop_resolution: ItemDropResolution | None = None
    username: str
    xp_gained: int
    # Portion of ``xp_gained`` that comes from the selected item's XP. The
    # engine computes it before delivery is confirmed; the fishing service
    # zeroes it when the item grant actually fails (plan section 9).
    item_xp_gained: int = 0
    mass_gained: Decimal
    is_level_up: bool
    old_level: int
    new_level: int
    fish_luck_factor_used: Decimal = Decimal("1")
    positive_fish_factor_used: Decimal = Decimal("1")
    negative_fish_factor_used: Decimal = Decimal("1")
    effective_percentage: Optional[Decimal] = None
    item_drop_probability: Optional[Decimal] = None
    item_drop_roll: Optional[Decimal] = None
    durability_loss: int = 1
    broken_item_name: Optional[str] = None
    robbery_result: Optional[RobberyResultDTO] = None
    roulette_result: Optional[RussianRouletteResultDTO] = None
    reward_roll_trace: Optional[Dict[str, Any]] = None
    item_roll_trace: Optional[Dict[str, Any]] = None
    rng_stages: List[Dict[str, Any]] = Field(default_factory=list)


class PlayerStatsDTO(BaseModel):
    level: int = 1
    xp: int = 0
    xp_to_next_level: int = 0
    current_mass: Decimal = Decimal("0.00")
    total_fish_stat: int = 0
    rod_name: str
    rank: int = 0
    total_mass_stat: Decimal = Decimal("0.00")
    # v2 concepts: human-percent change values resolved for the player.
    fish_luck_change_percent: Decimal = Decimal("0")
    positive_fish_reward_change_percent: Decimal = Decimal("0")
    negative_fish_reward_change_percent: Decimal = Decimal("0")
    xp_gain_change_percent: Decimal = Decimal("0")
    cooldown_change_percent: Decimal = Decimal("0")
    item_drop_chance_add_pp: Decimal = Decimal("0")
    item_rarity_luck_change_percent: Decimal = Decimal("0")
    robbery_protection_percent: Decimal = Decimal("0")
    robbery_evasion_percent: Decimal = Decimal("0")


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
    current_mass: Decimal = Decimal("0.00")
    total_fish_stat: int = 0
    total_mass_stat: Decimal


class FishTopResponse(BaseModel):
    success: bool
    chat_message: str
    mode: str = "current"
    top: List[TopPlayerDTO] = Field(default_factory=list)
