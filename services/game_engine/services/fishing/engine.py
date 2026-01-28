import random
import time
from domain.logic import rng, formulas, inventory_utils
from core.game_params import resolve_param, GParam
from domain.schemas.fishing import FishingResult, RobberyResultDTO
from infrastructure.models import UserProgress
from typing import Dict, Any

class FishingEngine:
    def calculate_result(self, user, loot_pool, item_pool, items_drop_rate, custom_params) -> FishingResult:
        equipped_rod = inventory_utils.find_equipped_rod(user.inventory or {})
        rod_stats = equipped_rod.get("stats", {}) if equipped_rod else {}
        luck = 1 + rod_stats.get("luck_bonus", 0.0)
        xp_bonus = rod_stats.get("xp_bonus_pct", 0.0)

        catch = rng.roll_loot(loot_pool, luck_modifier=luck)
        
        item_catch = None
        if item_pool and random.random() < items_drop_rate:
            item_catch = rng.roll_loot(item_pool, luck_modifier=luck)
            if item_catch:
                item_stats = item_catch.get("stats", {})
                item_catch.update({
                    "current_durability": item_stats.get("durability", 100),
                    "obtained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                })

        xp_gain = formulas.calculate_xp_gain(
            base_xp=catch.get("xp", 0),
            item_xp=item_catch.get("xp_gain", 0) if item_catch else 0,
            bonus_pct=xp_bonus
        )
        
        current_xp = user.xp + xp_gain
        is_levelup = self._check_level_up(current_xp, user.level, custom_params)
        new_level = user.level + 1 if is_levelup else user.level

        mass_gain = 0.0
        if catch.get("type") == "fish":
            mass_gain = self._calculate_mass(catch, luck)

        return FishingResult(
            loot=catch,
            item_drop=item_catch,
            username=user.username,
            xp_gained=xp_gain,
            mass_gained=mass_gain,
            is_level_up=is_levelup,
            new_level=new_level,
            luck_used=luck
        )
    
    def calculate_mass_robbery(self, attacker: UserProgress, victim: UserProgress, channel_config: Dict[str, Any], catch: Dict) -> RobberyResultDTO:
        min_chance = resolve_param(channel_config, GParam.ROB_MIN_CHANCE)       # 0.05
        max_chance = resolve_param(channel_config, GParam.ROB_MAX_CHANCE)       # 0.95
        resist_divisor = resolve_param(channel_config, GParam.ROB_RESIST_DIVISOR) # 100.0
        loss_divisor = resolve_param(channel_config, GParam.ROB_LOSS_DIVISOR)   # 50.0
        base_rob_chance = resolve_param(channel_config, GParam.ROB_BASE_CHANCE) # 0.8

        attacker_rod = inventory_utils.find_equipped_rod(attacker.inventory or {})
        rod_stats = attacker_rod.get("stats", {}) if attacker_rod else {}
        attacker_luck = 1.0 + rod_stats.get("luck_bonus", 0.0)

        victim_resistance = float(victim.level * 5)

        final_chance = formulas.calculate_robbery_chance(
            base_chance=base_rob_chance,
            attacker_luck=attacker_luck,
            victim_resistance=victim_resistance,
            resist_divisor=resist_divisor,
            min_chance=min_chance,
            max_chance=max_chance
        )

        is_success = random.random() < final_chance
        final_amount = 0.0

        if is_success:
            potential_loss = 0
            steal_percent = max(catch.get("percentage", 0), 0)
            if steal_percent > 0:
                potential_loss = victim.current_mass * steal_percent
            steal_value = max(catch.get("mass", 0), 0)
            if steal_value > 0:
                potential_loss += steal_value

            final_amount = formulas.calculate_robbery_loss(
                potential_loss=potential_loss,
                victim_resistance=victim_resistance,
                loss_divisor=loss_divisor
            )
            
            final_amount = round(min(final_amount, victim.current_mass), 2)

        return RobberyResultDTO(
            is_success=is_success,
            amount_stolen=final_amount,
            victim_name=victim.username,
            victim_twitch_id=victim.user_twitch_id,
            chance_used=round(final_chance, 3)
        )

    def _check_level_up(self, current_xp: int, user_level: int, custom_params: Dict[str, Any]) -> bool:
        xp_exponent = resolve_param(custom_params, GParam.XP_EXPONENT)
        xp_base = resolve_param(custom_params, GParam.XP_BASE)
        return formulas.is_level_up(
            current_xp=current_xp, 
            current_level=user_level,
            base=xp_base,
            exponent=xp_exponent
            )

    def _calculate_mass(self, catch: dict, luck_modifier: float) -> float:
        min_m = catch.get("min_mass", 0.1)
        max_m = catch.get("max_mass", 5.0)
        
        if catch.get("fixed_mass") is not None:
            raw_mass = catch.get("fixed_mass")
        else:
            raw_mass = random.uniform(min_m, max_m)
            
        if raw_mass < 0:
            return round(raw_mass / luck_modifier, 2)
        return round(raw_mass * luck_modifier, 2)