from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ResolvedFishingStrategy(BaseModel):
    cooldown_multiplier: float = 1.0
    override_loot_pool_location_id: Optional[str] = None
    modifiers: Dict[str, Any] = Field(default_factory=dict)
