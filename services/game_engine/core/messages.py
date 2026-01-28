from enum import Enum
import string
from typing import Dict, Any

class MsgKey(str, Enum):
    # --- Inventory ---
    EQUIP_SUCCESS = "equip_success"
    EQUIP_FAIL_NOT_FOUND = "equip_fail_not_found"
    EQUIP_FAIL_WRONG_TYPE = "equip_fail_wrong_type"
    INV_FULL = "inv_full"
    INV_EMPTY = "inv_empty"
    INV_LIST_HEADER = "inv_list_header"
    
    # --- Roulette ---
    ROULETTE_SHOT = "roulette_shot"
    ROULETTE_SAFE = "roulette_safe"
    
    # --- Points ---
    POINTS_SET = "points_set"
    POINTS_SET_FAIL = "points_set_fail"

    # --- Mass ---
    MASS_SET = "mass_set"

    # --- Level ---
    LEVEL_UP = "level_up"

    # --- Fishing ---
    FISH_BASE_MSG = "fish_base_msg"
    ITEM_CAUGHT = "item_caught"
    ROD_BROKEN = "rod_broken"
    NO_ROD_EQUIPPED = "no_rod_equipped"

    # --- Timeout ---
    TIMEOUT_ISSUED = "timeout_issued"
    TIMEOUT_ISSUED_FAIL = "timeout_issued_fail"

    # --- Robbery ---
    ROBBERY_SUCCESS = "robbery_success"
    ROBBERY_FAIL = "robbery_fail"
    ROBBERY_PROTECTED = "robbery_protected"
    ROBBERY_POOR = "robbery_poor"

    # --- Cooldown ---
    COOLDOWN_ACTIVE = "cooldown_active"
    COOLDOWN_OVER = "cooldown_over"

    # --- Economy (Selling) ---
    SELL_SUCCESS = "sell_success"
    SELL_FAIL_NOT_SELLABLE = "sell_fail_not_sellable"
    SELL_NOTHING = "sell_nothing"

    # --- Economy (Mass Exchange) ---
    SELL_MASS_SUCCESS = "sell_mass_success"
    SELL_MASS_EMPTY = "sell_mass_empty"
    SELL_MASS_DISABLED = "sell_mass_disabled"
    MARKET_INFO = "market_info"

    # --- Travel / Locations ---
    TRAVEL_SUCCESS = "travel_success"
    TRAVEL_FAIL_LEVEL = "travel_fail_level"
    TRAVEL_FAIL_NOT_FOUND = "travel_fail_not_found"
    CURRENT_LOCATION = "current_location"

    # --- Consumables ---
    BAIT_CONSUMED = "bait_consumed"
    
    # --- Errors ---
    ERR_NO_PROFILE = "err_no_profile"
    ERR_GENERIC = "err_generic"
    ERR_NO_POOL = "err_no_pool"
    ERR_NO_PERMISSION = "err_no_permission"

    # --- Info ---
    PROFILE_STATS = "profile_stats"
    HELP_TEXT = "help_text"


DEFAULT_MESSAGES = {
    # username - twitch user name
    # level - current user level
    # new_level - user level after leveling up
    # xp - experience points gained/user current xp
    # xp_next - experience points needed for next level
    # amount - amount of points/mass to add/substract
    # new_amount - new total amount of points
    # rate - current fish market rate
    # mass - mass of fish sold
    # current_mass - current mass of fish in user's inventory
    # new_mass - new total mass of fish
    # item_name - name of the item
    # quantity - quantity of the item
    # slot_id - inventory slot id
    # current - current number of items in inventory
    # max - maximum number of items in inventory/slots amount
    # location_name - name of the location
    # req_level - required level to enter location
    # duration - timeout duration
    # cooldown_time - total cooldown time
    # cooldown_time_left - remaining cooldown time
    # attacker - name of the robbery attacker
    # attacker_mass - robbery attackers current amount of fish mass
    # attacker_gain - robbery attackers fish mass gain
    # victim - name of the robbery victim
    # victim_mass - robbery victims current amount of fish mass
    # victim_loss - robbery victims fish mass loss
    # percent - percentage of points robbed
    # total_fish_stat - total number of fish caught by user
    # total_mass_stat - total mass of fish caught by user
    
    MsgKey.EQUIP_SUCCESS: "Equipped {item_name} [{slot_id}].",
    MsgKey.EQUIP_FAIL_NOT_FOUND: "Item in slot #{slot_id} not found.",
    MsgKey.EQUIP_FAIL_WRONG_TYPE: "Item {item_name} — is not a rod!",
    MsgKey.INV_FULL: "Your inventory is full ({current}/{max})! You couldn't keep {item_name}.",
    MsgKey.INV_EMPTY: "Inventory of {username} is empty.",
    MsgKey.INV_LIST_HEADER: "🎒 {username}'s Inventory:",
    
    MsgKey.ROULETTE_SHOT: "OUCH! {username} got shot!",
    MsgKey.ROULETTE_SAFE: "Click... {username} was lucky.",

    MsgKey.POINTS_SET: "Set {username} points to: {new_amount} ({amount}).",
    MsgKey.POINTS_SET_FAIL: "Failed to set points for {username}.",

    MsgKey.MASS_SET: "User {username} fish weight set to: {new_mass} ({amount}).",

    MsgKey.LEVEL_UP: "Congratulations {username}! You've reached level {new_level}!",

    MsgKey.FISH_BASE_MSG: "{username} is fishing... !fish",
    MsgKey.ITEM_CAUGHT: "Caught: {item_name} x{quantity}!",
    MsgKey.ROD_BROKEN: "CRACK! Your {item_name} snapped in half! It's gone forever.",
    MsgKey.NO_ROD_EQUIPPED: "You need a fishing rod to fish here! Equip one first (!fishequip).",

    MsgKey.TIMEOUT_ISSUED: "{username} has been timed out for {duration}!",
    MsgKey.TIMEOUT_ISSUED_FAIL: "Failed to timeout {username}.",

    MsgKey.ROBBERY_SUCCESS: "{attacker} {attackes_mass} ({attacker_gain}) robbed of {victim}'s pockets {victim_mass} ({victim_loss})!",
    MsgKey.ROBBERY_FAIL: "{attacker} tried to rob anyone, but failed!",
    MsgKey.ROBBERY_PROTECTED: "{attacker} tried to rob {victim}, but they were protected!",
    MsgKey.ROBBERY_POOR: "{attacker} tried to rob {victim}, but they have empty pockets!",

    MsgKey.COOLDOWN_ACTIVE: "Fish cooldown for {username} is {cooldown_time} ({cooldown_time_left} left)",
    MsgKey.COOLDOWN_OVER: "Fish cooldown for {username} is {cooldown_time}, ready to fish again!",

    MsgKey.SELL_SUCCESS: "Sold {item_name} x{quantity} for {amount} points.",
    MsgKey.SELL_FAIL_NOT_SELLABLE: "You cannot sell {item_name}, it's priceless!",
    MsgKey.SELL_NOTHING: "You have nothing to sell.",

    MsgKey.SELL_MASS_SUCCESS: "🐟 You sold {mass} of catch for {amount} points! (Rate: {rate}/kg).",   
    MsgKey.SELL_MASS_EMPTY: "Your net is empty (0kg). Catch some fish first!",    
    MsgKey.SELL_MASS_DISABLED: "The Fish Market is currently closed.",    
    MsgKey.MARKET_INFO: "📈 Current Fish Market Rate: {rate} points per 1kg.",    

    MsgKey.TRAVEL_SUCCESS: "You traveled to {location_name}.",
    MsgKey.TRAVEL_FAIL_LEVEL: "You need Level {req_level} to enter {location_name} (Current: {level}).",
    MsgKey.TRAVEL_FAIL_NOT_FOUND: "Location '{location_id}' does not exist.",
    MsgKey.CURRENT_LOCATION: "You are currently fishing at: {location_name}.",

    MsgKey.BAIT_CONSUMED: "Your {item_name} ran out!",

    MsgKey.ERR_NO_PROFILE: "No profile found for {username}. Start fishing first (!fish).",
    MsgKey.ERR_GENERIC: "An error occurred. Please try again later.",
    MsgKey.ERR_NO_POOL: "No loot pool configured for this channel/location.",
    MsgKey.ERR_NO_PERMISSION: "You don't have permission to do that.",

    MsgKey.PROFILE_STATS: "👤 {username} | Lvl: {level} | XP: {xp}/{xp_next} | Fish total weight: {current_mass} | Total fish gained: {total_mass_stat} | Amount of fish caught: {total_fish_stat}",
    MsgKey.HELP_TEXT: "Commands: !fish, !fishbag, !fishequip <slot>, !fishsell <slot>, !fishstats",
}

class SafeFormatter(string.Formatter):
    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            return kwargs.get(key, '{' + key + '}')
        return super().get_value(key, args, kwargs)
    

formatter = SafeFormatter()

def resolve_message(channel_config: Dict[str, Any], key: MsgKey, **kwargs) -> str:
    if not channel_config:
        channel_config = {}
        
    custom_messages = channel_config.get("messages", {})
    if isinstance(key, MsgKey):
        template = custom_messages.get(key.value)
        if not template:
            template = DEFAULT_MESSAGES.get(key, f"Missing text: {key.value}")
    else:
        template = key

    try:
        return formatter.format(template, **kwargs)
    except Exception as e:
        return f"{template} (Format Error: {e})"
    
def format_large_number_mass(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000_000_000:
        value = value / 1_000_000_000_000_000
        return f"{value:.2f}".rstrip('0').rstrip('.') + "Tt"
    elif abs_value >= 1_000_000_000_000:
        value = value / 1_000_000_000_000
        return f"{value:.2f}".rstrip('0').rstrip('.') + "Gt"
    elif abs_value >= 1_000_000_000:
        value = value / 1_000_000_000
        return f"{value:.2f}".rstrip('0').rstrip('.') + "Mt"
    elif abs_value >= 1_000_000:
        value = value / 1_000_000
        return f"{value:.2f}".rstrip('0').rstrip('.') + "kt"
    elif abs_value >= 1_000:
        value = value / 1_000
        return f"{value:.2f}".rstrip('0').rstrip('.') + "t"
    else:
        return f"{value:.2f}".rstrip('0').rstrip('.') + "kg"

def format_large_number_mass_signed(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    formatted_value = format_large_number_mass(abs(value))
    return f"{sign}{formatted_value}"

def format_large_number_points(value) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000_000_000_000:
        value = value / 1_000_000_000_000_000
        return f"{value:.2f}".rstrip('0').rstrip('.') + "Q"
    elif abs_value >= 1_000_000_000_000:
        value = value / 1_000_000_000_000
        return f"{value:.2f}".rstrip('0').rstrip('.') + "T"
    elif abs_value >= 1_000_000_000:
        value = value / 1_000_000_000
        return f"{value:.2f}".rstrip('0').rstrip('.') + "B"
    elif abs_value >= 1_000_000:
        value = value / 1_000_000
        return f"{value:.2f}".rstrip('0').rstrip('.') + "M"
    elif abs_value >= 1_000:
        value = value / 1_000
        return f"{value:.2f}".rstrip('0').rstrip('.') + "K"
    else:
        return f"{value:.2f}".rstrip('0').rstrip('.')

def format_large_number_points_signed(value) -> str:
    sign = "+" if value >= 0 else "-"
    formatted_value = format_large_number_points(abs(value))
    return f"{sign}{formatted_value}"

def format_time(seconds):
    seconds = int(seconds)

    days = seconds // 86400
    seconds %= 86400

    hours = seconds // 3600
    seconds %= 3600

    minutes = seconds // 60
    seconds %= 60

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")

    return ' '.join(parts)

def format_percent(value):
    percent = abs(value) * 100
    formatted = f"{percent:.2f}".rstrip('0').rstrip('.')
    return f"{formatted}%"

def format_percent_signed(value):
    sign = "+" if value >= 0 else "-"
    percent = abs(value) * 100
    formatted = f"{percent:.2f}".rstrip('0').rstrip('.')
    return f"{sign}{formatted}%"