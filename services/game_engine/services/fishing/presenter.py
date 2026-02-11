from typing import List, Dict, Any

from core.messages import (
    resolve_message, MsgKey, 
    format_large_number_mass, format_large_number_mass_signed, 
    format_time, format_large_number_points, format_percent, format_percent_signed
)
from core.action_types import ActionType

from domain.schemas.actions import (
    GameAction,
    TimeoutAction, 
    StreamElementsPointsAction, 
    RobberyAction, 
    AddMassAction, 
    SendBaseMessageAction, 
    LevelUpAction,
    AddItemAction
)
from domain.schemas.fishing import FishResponse, LevelUpInfo, FishingResult
from infrastructure.models import UserProgress

import random

class FishingPresenter:

    def build_response(self, user: UserProgress, result: FishingResult) -> FishResponse:
        actions: List[GameAction] = []
        channel_conf = user.channel.config or {}
        catch_type = result.loot.get("type", "fish")
        
        if catch_type == ActionType.NOTHING:
            actions.append(self._present_basic_msg(user, result, channel_conf, username=user.username))

        elif catch_type == ActionType.FISH:
            actions.extend(self._present_fish(user, result, channel_conf))
            
        elif catch_type == ActionType.TIMEOUT:
            actions.extend(self._present_timeout(user, result, channel_conf))
            
        elif catch_type == ActionType.POINTS:
            actions.extend(self._present_points(user, result, channel_conf))
            
        elif catch_type == ActionType.ROBBERY:
            actions.extend(self._present_robbery(user, result, channel_conf))
            
        elif catch_type == ActionType.RUSSIAN_ROULETTE:
            actions.extend(self._present_roulette(user, result, channel_conf))
        

        if result.item_drop:
            item_actions = self._present_item_drop(user, result.item_drop, channel_conf)
            actions.extend(item_actions)
        
        if result.is_level_up:
            lvl_actions = self._present_level_up(user, result.new_level, channel_conf)
            actions.extend(lvl_actions)

        main_chat_message = "You caught something!"
        base_msg_action = next((a for a in actions if a.type == ActionType.BASE_MESSAGE), None)
        
        if base_msg_action and base_msg_action.action_message:
            main_chat_message = base_msg_action.action_message

        return FishResponse(
            chat_message=main_chat_message,
            xp_gained=result.xp_gained,
            item_drop=None, 
            level_up=LevelUpInfo(old_level=user.level-1, new_level=result.new_level) if result.is_level_up else None,
            actions=actions
        )


    def _present_basic_msg(self, user: UserProgress, result: FishingResult, config: Dict, **kwargs) -> SendBaseMessageAction:
        base_msg = resolve_message(config, MsgKey.FISH_BASE_MSG, **kwargs)
        catch_msg = resolve_message(config, result.loot.get("message", ""), **kwargs)
        full_message = f"{base_msg} {catch_msg}"
        return SendBaseMessageAction(action_message=full_message)        


    def _present_fish(self, user: UserProgress, result: FishingResult, config: Dict) -> List[GameAction]:
        actions = []
        
        mass_formatted = format_large_number_mass_signed(result.mass_gained)
        new_mass_formatted = format_large_number_mass(user.current_mass)
        
        percentage = 0
        if result.loot.get("percentage") is not None:
            percentage = result.loot.get("percentage")
            if percentage >= 0:
                percentage *= max(1, result.luck_used)
            else:
                percentage /= max(1, result.luck_used)
        percentage_formatted = format_percent_signed(percentage)

        base_msg_action = self._present_basic_msg(
            user, result, config, 
            username=user.username, amount=mass_formatted, new_mass=new_mass_formatted,
            percentage=percentage_formatted
            )

        actions.append(base_msg_action)

        mass_update_msg = resolve_message(
            config, MsgKey.MASS_SET,
            amount=mass_formatted,
            new_mass=new_mass_formatted,
            username=user.username
        )
        
        actions.append(AddMassAction(
            amount=result.mass_gained,
            amount_now=round(user.current_mass, 2),
            total_mass=round(user.total_mass_stat, 2),
            action_message=mass_update_msg
        ))
        
        return actions

    def _present_timeout(self, user: UserProgress, result: FishingResult, config: Dict) -> List[GameAction]:
        duration = result.loot.get("duration", 60)
        reason = result.loot.get("reason", "No reason")
        formatted_dur = format_time(duration)
        
        base_msg_action = self._present_basic_msg(
            user, result, config, 
            username=user.username, duration=formatted_dur, reason=reason
            )

        msg_text = resolve_message(
            config, MsgKey.TIMEOUT_ISSUED,
            username=user.username,
            duration=formatted_dur,
            reason=reason
        )
        
        timeout_action = TimeoutAction(
            duration=duration,
            reason=reason,
            target_user=user.username,
            action_message=msg_text
        )
        
        return [base_msg_action, timeout_action]

    def _present_points(self, user: UserProgress, result: FishingResult, config: Dict) -> List[GameAction]:
        points = result.loot.get("value", 0)
        
        action = StreamElementsPointsAction(
            amount=points,
            target_user=result.loot.get("target_user", user.user_twitch_id),
            action_message=result.loot.get("action_message", "")
        )
        if result.loot.get("message"):
            formatted_pts = format_large_number_points(points)
            msg = resolve_message(config, result.loot["message"], username=user.username, points=formatted_pts)
            return [SendBaseMessageAction(action_message=msg), action]
            
        return [action]

    def _present_robbery(self, user: UserProgress, result: FishingResult, config: Dict) -> List[GameAction]:
        actions = []

        percent = result.loot.get("percentage", 0)
        amount = result.loot.get("mass", 0)
        robbery_result = result.robbery_result

        base_msg_action = self._present_basic_msg(
            user, result, config, 
            username=user.username, percentage=percent, mass=amount
            )
        
        actions.append(base_msg_action)

        if not robbery_result:
            msg = resolve_message(config, MsgKey.ROBBERY_FAIL, attacker=user.username)
            actions.append(SendBaseMessageAction(action_message=msg))
            return actions

        if robbery_result.is_success:
            amount_gain_fmt = format_large_number_mass_signed(robbery_result.amount_stolen)
            amount_lost_fmt = format_large_number_mass_signed(0 - robbery_result.amount_stolen)
            attacker_mass_fmt = format_large_number_mass(user.current_mass)
            victim_mass_fmt = format_large_number_mass(robbery_result.victim_new_mass)

            msg_text = resolve_message(
                config, 
                MsgKey.ROBBERY_SUCCESS,
                attacker=user.username,
                attackes_mass=attacker_mass_fmt,
                victim=robbery_result.victim_name,
                attacker_gain=amount_gain_fmt,
                victim_mass=victim_mass_fmt,
                victim_loss=amount_lost_fmt
            )
            
            actions.append(SendBaseMessageAction(action_message=msg_text))

            actions.append(AddMassAction(
                amount=robbery_result.amount_stolen,
                amount_now=round(user.current_mass, 2),
                total_mass=round(user.total_mass_stat, 2),
                action_message=""
            ))

        else:
            msg_text = resolve_message(
                config, 
                MsgKey.ROBBERY_PROTECTED,
                attacker=user.username,
                victim=robbery_result.victim_name
            )
            actions.append(SendBaseMessageAction(action_message=msg_text))

        return actions

    def _present_roulette(self, user: UserProgress, result: FishingResult, config: Dict) -> List[GameAction]:
        roulette = result.roulette_result
        if roulette:
            is_hit = roulette.is_hit
            final_msg_template = roulette.message
            active_effect = roulette.penalty if is_hit else roulette.reward
        else:
            bullets = max(int(result.loot.get("bullets", 1)), 0)
            chambers = max(int(result.loot.get("chambers", 6)), 1)
            is_hit = random.random() < (bullets / chambers)
            message_key = "shot_message" if is_hit else "safe_message"
            final_msg_template = result.loot.get(message_key, "Click..." if not is_hit else "BANG!")
            active_effect = result.loot.get("penalty", {}) if is_hit else result.loot.get("reward", {})

        if not final_msg_template:
            fallback_key = MsgKey.ROULETTE_SHOT if is_hit else MsgKey.ROULETTE_SAFE
            final_msg_template = resolve_message(config, fallback_key, username=user.username)

        actions: List[GameAction] = []
        active_effect = active_effect if isinstance(active_effect, dict) else {}

        mass_formatted = format_large_number_mass_signed(result.mass_gained)
        new_mass_formatted = format_large_number_mass(user.current_mass)

        percentage_value = float(active_effect.get("percentage", 0) or 0)
        if percentage_value != 0:
            if percentage_value >= 0:
                percentage_value *= max(1, result.luck_used)
            else:
                percentage_value /= max(1, result.luck_used)
        percentage_formatted = format_percent_signed(percentage_value)

        timeout_duration = int(active_effect.get("duration", 0) or 0)
        duration_formatted = format_time(timeout_duration) if timeout_duration > 0 else "0s"
        timeout_reason = active_effect.get("reason", "Roulette Death")

        final_msg = resolve_message(
            config,
            final_msg_template,
            username=user.username,
            amount=mass_formatted,
            mass=mass_formatted,
            new_mass=new_mass_formatted,
            percentage=percentage_formatted,
            percent=percentage_formatted,
            duration=duration_formatted,
            reason=timeout_reason
        )
        actions.append(SendBaseMessageAction(action_message=final_msg))

        effect_type = str(active_effect.get("type", "")).lower()
        if effect_type == "timeout":
            duration = int(active_effect.get("duration", 60))
            reason = active_effect.get("reason", "Roulette Death")
            timeout_msg = resolve_message(
                config, MsgKey.TIMEOUT_ISSUED,
                username=user.username,
                duration=format_time(duration),
                reason=reason
            )
            actions.append(TimeoutAction(
                duration=duration,
                reason=reason,
                target_user=user.username,
                action_message=timeout_msg
            ))

        if result.mass_gained != 0:
            mass_update_msg = resolve_message(
                config, MsgKey.MASS_SET,
                amount=mass_formatted,
                new_mass=new_mass_formatted,
                username=user.username
            )
            actions.append(AddMassAction(
                amount=result.mass_gained,
                amount_now=round(user.current_mass, 2),
                total_mass=round(user.total_mass_stat, 2),
                action_message=mass_update_msg
            ))

        return actions

    def _present_item_drop(self, user: UserProgress, item: Dict, config: Dict) -> List[GameAction]:
        item_name = item.get("name", "Unknown Item")
        quantity = item.get("quantity", 1)
        
        msg = resolve_message(
            config, MsgKey.ITEM_CAUGHT, 
            username=user.username, 
            item_name=item_name, 
            quantity=quantity
        )
        
        add_action = AddItemAction(
            item_id=item.get("item_id"),
            item_name=item_name,
            quantity=quantity,
            action_message=msg
        )
        
        return [add_action]

    def _present_level_up(self, user: UserProgress, new_level: int, config: Dict) -> List[GameAction]:
        msg = resolve_message(
            config, MsgKey.LEVEL_UP, 
            username=user.username, 
            new_level=new_level
        )
    
        return [LevelUpAction(new_level=new_level, action_message=msg)]
