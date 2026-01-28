from infrastructure.repositories import UserRepository, ConfigRepository
from infrastructure.models import UserProgress

from core.action_types import ActionType

from services.fishing.engine import FishingEngine
from services.fishing.presenter import FishingPresenter

from domain.schemas.fishing import RobberyResultDTO

class FishingService:
    def __init__(self, user_repo: UserRepository, config_repo: ConfigRepository):
        self.user_repo = user_repo
        self.config_repo = config_repo
        self.engine = FishingEngine()
        self.presenter = FishingPresenter()

    def process_cast(self, twitch_id: str, username: str, channel_id: str):
        user = self.user_repo.get_progress(twitch_id, channel_id)
        if not user:
            user = self.user_repo.create(twitch_id, username, channel_id)
            
        location_id = user.current_location_id or "default"
        loot_pool, item_pool, rate = self.config_repo.get_dual_pool(channel_id, location_id)

        result = self.engine.calculate_result(
            user=user, 
            loot_pool=loot_pool, 
            item_pool=item_pool, 
            items_drop_rate=rate,
            custom_params=user.channel.config.get("custom_params", {})
        )

        if result.loot.get("type") == ActionType.ROBBERY:
            result.robbery_result = self._handle_robbery(result.loot, user)

        user.xp += result.xp_gained
        user.total_fish_stat += 1
        
        if result.is_level_up:
            user.level = result.new_level
            
        if result.mass_gained != 0:
            user.current_mass += result.mass_gained
            user.total_mass_stat += result.mass_gained
            
        if result.item_drop:
            self.user_repo.update_inventory(user, result.item_drop)

        self.user_repo.save_progress(user)

        response = self.presenter.build_response(user, result)
        
        return response
    
    def _handle_robbery(self, loot: dict, user: UserProgress) -> RobberyResultDTO:
        lookup_range = loot.get("range", 3)
        channel_config = user.channel.config or {}

        victim = self.user_repo.get_rich_victim(
            channel_id=user.channel.id,
            attacker_id=user.id,
            lookup_range=lookup_range
        )        

        robbery_result = self.engine.calculate_mass_robbery(
            attacker=user,
            victim=victim,
            channel_config=channel_config,
            catch=loot
        )

        if robbery_result.is_success:
            user.current_mass += robbery_result.amount_stolen
            user.total_mass_stat += robbery_result.amount_stolen
            victim.current_mass -= robbery_result.amount_stolen
            victim.total_mass_stat -= robbery_result.amount_stolen
            self.user_repo.save_progress(victim)
        
        return robbery_result
