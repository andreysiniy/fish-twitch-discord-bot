from enum import Enum
from typing import Dict, Any, Union

class GParam(str, Enum):
    # --- XP ---
    XP_BASE = "xp_base"             # 100
    XP_EXPONENT = "xp_exponent"     # 1.5
    
    # --- Sell Price ---
    SELL_MAX_BONUS = "sell_max_bonus" # 2.0 (max bonus multiplier)
    SELL_MID_LEVEL = "sell_mid_level" # 50 (level where bonus is half of max)

    # --- Robbery ---
    ROB_MIN_CHANCE = "rob_min_chance" # 0.05
    ROB_MAX_CHANCE = "rob_max_chance" # 0.95
    ROB_RESIST_DIVISOR = "rob_resist_divisor" # 100 (divisor for resistance)
    ROB_LOSS_DIVISOR = "rob_loss_divisor" # 50 (divisor for loss)

DEFAULT_GAME_PARAMS: Dict[GParam, Union[int, float]] = {
    GParam.XP_BASE: 100,
    GParam.XP_EXPONENT: 1.5,
    
    GParam.SELL_MAX_BONUS: 2.0,
    GParam.SELL_MID_LEVEL: 50,
    
    GParam.ROB_MIN_CHANCE: 0.05,
    GParam.ROB_MAX_CHANCE: 0.95,
    GParam.ROB_RESIST_DIVISOR: 100.0,
    GParam.ROB_LOSS_DIVISOR: 50.0,
}

def resolve_param(channel_config: Dict[str, Any], key: GParam) -> float:
    if not channel_config:
        return DEFAULT_GAME_PARAMS[key]
        
    custom_params = channel_config.get("game_params", {})
    val = custom_params.get(key.value)
    
    if val is None:
        return DEFAULT_GAME_PARAMS[key]
        
    return float(val)