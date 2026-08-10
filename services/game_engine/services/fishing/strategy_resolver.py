from dataclasses import dataclass
from infrastructure.repositories.channel_repo import ChannelRepository
from services.fishing.engine import CalculationStrategy, DefaultLootStrategy


@dataclass
class ResolvedFishingStrategy:
    calculation_strategy: CalculationStrategy
    override_loot_pool_location_id: str | None


class FishingStrategyResolver:
    def __init__(self, channel_repo: ChannelRepository):
        self.channel_repo = channel_repo

    def resolve(self, channel_id: int) -> ResolvedFishingStrategy:
        event = self.channel_repo.get_active_fishing_event(channel_id)
        return ResolvedFishingStrategy(
            calculation_strategy=DefaultLootStrategy(),
            override_loot_pool_location_id=(event.override_loot_pool if event else None),
        )
