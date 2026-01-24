from infrastructure.repositories import UserRepository, ConfigRepository

from services.fishing.engine import FishingEngine
from services.fishing.presenter import FishingPresenter

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