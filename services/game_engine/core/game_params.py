from enum import Enum
from typing import Dict, Any, Union

class GParam(str, Enum):
    # --- XP ---
    XP_BASE = "xp_base"             # 100
    XP_EXPONENT = "xp_exponent"     # 1.5
    
    # --- Robbery ---
    ROB_MIN_CHANCE = "rob_min_chance" # 0.05
    ROB_MAX_CHANCE = "rob_max_chance" # 0.95
    ROB_BASE_CHANCE = "rob_base_chance"

    # --- Cooldown ---
    FISHING_COOLDOWN = "fishing_cooldown" # in seconds
    SUBS_FISHING_COOLDOWN = "subs_fishing_cooldown" # in seconds


DEFAULT_GAME_PARAMS: Dict[GParam, Union[int, float]] = {
    GParam.XP_BASE: 100,
    GParam.XP_EXPONENT: 1.5,
    
    GParam.ROB_MIN_CHANCE: 0.05,
    GParam.ROB_MAX_CHANCE: 0.95,
    GParam.ROB_BASE_CHANCE: 0.8,

    GParam.FISHING_COOLDOWN: 600,
    GParam.SUBS_FISHING_COOLDOWN: 300
}

def resolve_param(custom_params: Dict[str, Any], key: GParam) -> float:
    if not custom_params:
        return DEFAULT_GAME_PARAMS[key]
        
    #custom_params = channel_config.get("game_params", {})
    val = custom_params.get(key.value)
    
    if val is None:
        return DEFAULT_GAME_PARAMS[key]
        
    return float(val)
