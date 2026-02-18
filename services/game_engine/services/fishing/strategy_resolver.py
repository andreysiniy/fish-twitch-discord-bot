from dataclasses import dataclass
from typing import Any, Dict, Optional

from infrastructure.repositories.channel_repo import ChannelRepository
from services.fishing.engine import CalculationStrategy, EventLootStrategy, DefaultLootStrategy


@dataclass
class ResolvedFishingStrategy:
    calculation_strategy: CalculationStrategy
    cooldown_multiplier: float
    override_loot_pool_location_id: Optional[str]
    modifiers: Dict[str, Any]


class FishingStrategyResolver:
    def __init__(self, channel_repo: ChannelRepository):
        self.channel_repo = channel_repo

    def resolve(self, channel_id: int) -> ResolvedFishingStrategy:
        event = self.channel_repo.get_active_fishing_event(channel_id)
        if not event:
            return ResolvedFishingStrategy(
                calculation_strategy=DefaultLootStrategy(),
                cooldown_multiplier=1.0,
                override_loot_pool_location_id=None,
                modifiers={},
            )

        modifiers = dict(event.modifiers or {})
        strategy = EventLootStrategy(modifiers=modifiers)

        cd_reduction = float(modifiers.get("cd_reduction", 0.0) or 0.0)
        cd_reduction = min(max(cd_reduction, 0.0), 0.95)
        cooldown_multiplier = round(1.0 - cd_reduction, 4)

        override_pool_id = event.override_loot_pool

        return ResolvedFishingStrategy(
            calculation_strategy=strategy,
            cooldown_multiplier=cooldown_multiplier,
            override_loot_pool_location_id=override_pool_id,
            modifiers=modifiers,
        )
