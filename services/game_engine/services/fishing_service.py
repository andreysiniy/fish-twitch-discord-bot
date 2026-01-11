from domain.logic import rng, formulas
from domain.schemas.fishing import FishResponse, LevelUpInfo

from infrastructure.repositories import UserRepository, ConfigRepository
from domain.schemas.actions import TimeoutAction

class FishingService:
    def __init__(self, user_repo: UserRepository, config_repo: ConfigRepository):
        self.user_repo = user_repo
        self.config_repo = config_repo

    def process_cast(self, twitch_id: str, username: str, channel_id: str):
        user = self.user_repo.get_progress(twitch_id, channel_id)
        if not user:
            user = self.user_repo.create(twitch_id, username, channel_id)
            

        location_id = user.current_location_id or "default"
        loot_pool = self.config_repo.get_pool(channel_id, location_id)
        

        equipped_rod = user.inventory.get("equipped_rod")
        if not equipped_rod:
            equipped_rod = {"name": "bare hands", "luck": 1.0}
        catch = rng.roll_loot(loot_pool, luck_modifier=equipped_rod.get("luck", 1.0))
        

        xp_gain = catch.get("xp", 10)
        user.xp += xp_gain
        leveled_up = formulas.is_level_up(user.xp, user.level)
        
        if leveled_up:
            user.level += 1
            

        self.user_repo.save_progress(user)

        actions_to_perform = []
        actions_to_perform.append(
            TimeoutAction(duration=60, reason="Caught a boot") # Mock action
        )       
        

        return FishResponse(
            chat_message=f"{user.username} caught a {catch.get('name', 'mystery item')}!",
            xp_gained=xp_gain,
            money_change=catch.get("money", 0),
            item_drop=catch.get("item"),
            level_up=LevelUpInfo(
                old_level=user.level - 1,
                new_level=user.level,
                rewards=[]
            ) if leveled_up else None,
            actions=actions_to_perform
        )