from infrastructure.repositories import UserRepository, ConfigRepository
from infrastructure.repositories.cooldown_repo import CooldownRepository
from infrastructure.models import UserProgress

from core.action_types import ActionType
from core.game_params import GParam, resolve_param

from services.fishing.engine import FishingEngine
from services.fishing.presenter import FishingPresenter

from domain.schemas.fishing import RobberyResultDTO

class FishingService:
    def __init__(
        self,
        user_repo: UserRepository,
        config_repo: ConfigRepository,
        cooldown_repo: CooldownRepository
    ):
        self.user_repo = user_repo
        self.config_repo = config_repo
        self.cooldown_repo = cooldown_repo
        self.engine = FishingEngine()
        self.presenter = FishingPresenter()

    def process_cast(
        self,
        twitch_id: str,
        username: str,
        channel_id: str,
        is_mod: bool = False,
        is_sub: bool = False
    ):
        user = self.user_repo.get_progress(twitch_id, channel_id)
        if not user:
            user = self.user_repo.create(twitch_id, username, channel_id)

        channel_config = user.channel.config or {}
        custom_params = channel_config.get("custom_params", {})
        cooldown_duration = self._resolve_cooldown_duration(custom_params, is_mod, is_sub)

        if cooldown_duration > 0:
            is_active, seconds_left = self.cooldown_repo.check_cooldown(channel_id, twitch_id)
            if is_active:
                return self.presenter.build_cooldown_response(
                    user=user,
                    cooldown_duration=cooldown_duration,
                    cooldown_left=seconds_left
                )
            
        location_id = user.current_location_id or "default"
        loot_pool, item_pool, rate = self.config_repo.get_dual_pool(channel_id, location_id)

        result = self.engine.calculate_result(
            user=user, 
            loot_pool=loot_pool, 
            item_pool=item_pool, 
            items_drop_rate=rate,
            custom_params=custom_params
        )

        if result.loot.get("type") == ActionType.ROBBERY:
            result.robbery_result = self._handle_robbery(result.loot, user)

        user.xp += result.xp_gained
        user.total_fish_stat += 1
        
        if result.is_level_up:
            user.level = result.new_level
            
        if result.mass_gained != 0:
            previous_mass = user.current_mass
            user.current_mass = max(previous_mass + result.mass_gained, 0.0)
            applied_mass_delta = round(user.current_mass - previous_mass, 2)
            user.total_mass_stat += applied_mass_delta
            result.mass_gained = applied_mass_delta
            
        if result.item_drop:
            self.user_repo.update_inventory(user, result.item_drop)

        self.user_repo.save_progress(user)
        if cooldown_duration > 0:
            self.cooldown_repo.set_cooldown(channel_id, twitch_id, cooldown_duration)

        response = self.presenter.build_response(user, result)
        
        return response

    def _resolve_cooldown_duration(self, custom_params: dict, is_mod: bool, is_sub: bool) -> int:
        if is_mod:
            return 0

        cooldown_key = GParam.SUBS_FISHING_COOLDOWN if is_sub else GParam.FISHING_COOLDOWN
        return max(int(resolve_param(custom_params, cooldown_key)), 0)
    
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
            requested_stolen = max(float(robbery_result.amount_stolen or 0), 0.0)
            victim_previous_mass = max(float(victim.current_mass or 0), 0.0)
            applied_stolen = round(min(requested_stolen, victim_previous_mass), 2)

            user.current_mass += applied_stolen
            user.total_mass_stat += applied_stolen

            victim.current_mass = round(max(victim_previous_mass - applied_stolen, 0.0), 2)
            victim.total_mass_stat -= applied_stolen

            robbery_result.amount_stolen = applied_stolen
            robbery_result.victim_new_mass = victim.current_mass
            self.user_repo.save_progress(victim)
        
        return robbery_result
