import random
import time
from domain.logic import rng, formulas
from domain.schemas.fishing import FishResponse, LevelUpInfo
from domain.schemas.rpg import DropItemDTO, InventoryItemDTO
from domain.logic.inventory_utils import find_equipped_rod

from infrastructure.repositories import UserRepository, ConfigRepository
from domain.schemas.actions import TimeoutAction, RobberyAction, StreamElementsPointsAction, RussianRouletteAction, AddMassAction
from infrastructure.models import UserProgress

class FishingService:
    def __init__(self, user_repo: UserRepository, config_repo: ConfigRepository):
        self.user_repo = user_repo
        self.config_repo = config_repo

    def process_cast(self, twitch_id: str, username: str, channel_id: str):
        user = self.user_repo.get_progress(twitch_id, channel_id)
        if not user:
            user = self.user_repo.create(twitch_id, username, channel_id)
            

        location_id = user.current_location_id or "default"
        #loot_pool = self.config_repo.get_pool(channel_id, location_id)
        
        loot_pool, item_pool, items_drop_rate = self.config_repo.get_dual_pool(channel_id, location_id)


        equipped_rod = find_equipped_rod(user.inventory or {})
        equipped_rod_stats = equipped_rod.get("stats", {}) if equipped_rod else {}
        if not equipped_rod:
            equipped_rod = {"name": "bare hands", "stats": {}}
        luck = 1 + equipped_rod_stats.get("luck_bonus", 0)
        catch = rng.roll_loot(loot_pool, luck_modifier=luck)
        
        item_catch = None
        if item_pool and random.random() < items_drop_rate:
            item_catch = rng.roll_loot(item_pool, luck_modifier=luck)
        if item_catch:
            item_stats = item_catch.get("stats", {})
            item_catch.update({
                "current_durability": item_stats.get("durability", 1),
                "obtained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            })
            self.user_repo.update_inventory(user, item_catch)

        xp_gain = catch.get("xp", 10) + (item_catch.get("xp_gain", 0) if item_catch else 0)
        xp_gain = int(xp_gain * equipped_rod_stats.get("xp_bonus_pct", 0)) + xp_gain
        user.xp += xp_gain
        leveled_up = formulas.is_level_up(user.xp, user.level)
        print(f"User {twitch_id} gained {xp_gain} XP (Level {user.level} -> {user.level + 1 if leveled_up else user.level})")
        if leveled_up:
            user.level += 1

        user.total_fish_stat += 1
        actions_to_perform = self.get_actions(catch, user, luck_modifier=equipped_rod.get("luck", 1.0))  
        self.user_repo.save_progress(user)
    
        return FishResponse(
            chat_message=catch.get("message", "You caught something!"),
            xp_gained=xp_gain,
            money_change=catch.get("money", 0),
            item_drop=item_catch if item_catch else None,
            level_up=LevelUpInfo(
                old_level=user.level - 1,
                new_level=user.level,
                rewards=[]
            ) if leveled_up else None,
            actions=actions_to_perform
        )

    def get_actions(self, catch: dict, user: UserProgress, luck_modifier: float = 1.0) -> list:
        actions = []
        twitch_id = user.user_twitch_id
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
        if catch.get("type") == "fish":
            mass_action = self.handle_fish_mass(catch, user, luck_modifier)
            actions.append(mass_action)
        return actions
    
    def handle_fish_mass(self, catch: dict, user: UserProgress, luck_modifier: float) -> AddMassAction:
        min_m = catch.get("min_mass", 0.1)
        max_m = catch.get("max_mass", 5.0)
        if catch.get("fixed_mass") is not None:
            min_m = max_m = catch.get("fixed_mass")
        raw_mass = random.uniform(min_m, max_m)
        if raw_mass < 0:
            mass_gain = round(raw_mass / luck_modifier, 2)
        else:
            mass_gain = round(raw_mass * luck_modifier, 2)
        
        user.current_mass += mass_gain
        user.total_mass_stat += mass_gain
        
        return AddMassAction(
            amount=mass_gain,
            amount_now=round(user.current_mass, 2),
            action_message=catch.get("action_message", ""),
            total_mass=round(user.total_mass_stat, 2)
        )

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