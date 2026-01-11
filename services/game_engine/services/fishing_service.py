import random

from domain.logic import rng, formulas
from domain.schemas.fishing import FishResponse, LevelUpInfo

from infrastructure.repositories import UserRepository, ConfigRepository
from domain.schemas.actions import TimeoutAction, RobberyAction, StreamElementsPointsAction, RussianRouletteAction

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

        actions_to_perform = self.get_actions(catch, twitch_id)      
        
        return FishResponse(
            chat_message=catch.get("base_message", "You caught something!"),
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
    
    def get_actions(self, catch: dict, twitch_id: str) -> list:
        actions = []
        if catch.get("type") == "timeout":
            actions.append(TimeoutAction(
                duration=catch.get("duration", 30), 
                reason=catch.get("reason", "No reason"),
                action_message=catch.get("action_message", "")
                )
            )
        if catch.get("type") == "points":
            actions.append(StreamElementsPointsAction(
                amount=catch.get("value", 0), 
                target_user=catch.get("target_user", twitch_id),
                action_message=catch.get("action_message", "")
                )
            )
        if catch.get("type") == "robbery":
            actions.append(RobberyAction(
                attacker_id=twitch_id,
                victim_scope=catch.get("victim_scope", "active"), 
                steal_percent=catch.get("percent", 0),
                action_message=catch.get("action_message", "")
                )
            )
        if catch.get("type") == "russian_roulette":
            rr_action = self.handle_russian_roulette(catch, twitch_id)
            actions.append(rr_action)
        return actions

    def handle_russian_roulette(self, catch: dict, twitch_id: str) -> RussianRouletteAction:

        chambers = catch.get("chambers", 6)
        bullets = catch.get("bullets", 1)

        is_hit = random.random() < (bullets / chambers)
        penalty_action = None

        final_message = catch.get("safe_message", "Click... You're safe!")

        if is_hit:
            final_message = catch.get("shot_message", "Bang! You've been hit!")
            penalty = catch.get("penalty", {})
            penalty_type = penalty.get("type")

            if penalty_type == "timeout":
                penalty_action = TimeoutAction(
                    duration=penalty.get("duration", 60),
                    reason=penalty.get("reason", "Roulette"),
                    action_message=penalty.get("action_message", "")
                )
            
            if penalty_type == "points":
                penalty_action = StreamElementsPointsAction(
                    amount=penalty.get("value", -100),
                    action_message=penalty.get("action_message", "")
                )
        
        action = RussianRouletteAction(
            hit=is_hit,
            penalty_action=penalty_action,
            action_message=final_message
        )
        return action