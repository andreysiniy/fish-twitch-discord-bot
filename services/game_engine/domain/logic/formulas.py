import random

def calculate_xp_required(level: int, base: int = 100, exponent: float = 1.5) -> int:
    """XP = base * (level ^ exponent)"""
    return int(base * (level ** exponent))

def is_level_up(current_xp: int, current_level: int, base: int = 100, exponent: float = 1.5) -> bool:
    return current_xp >= calculate_xp_required(current_level, base, exponent)

def calculate_xp_gain(base_xp: int, item_xp: int, bonus_pct: float) -> int:
    total_base = base_xp + item_xp
    return int(total_base * (1 + bonus_pct))

def calculate_final_mass(
        min_mass: float, 
        max_mass: float, 
        luck_modifier: float, 
        fixed_mass: float = None
    ) -> float:
    
    if fixed_mass is not None:
        raw_mass = fixed_mass
    else:
        raw_mass = random.uniform(min_mass, max_mass)
    
    if raw_mass < 0:
        return round(raw_mass / luck_modifier, 2)
    
    return round(raw_mass * luck_modifier, 2)

def calculate_sell_price(
    mass: float, 
    rate: float, 
    level: int,
    max_bonus: float = 2.0,
    mid_level: int = 50
) -> int:
    base_value = mass * rate
    level_factor = 1 + (max_bonus * level / (level + mid_level))
    return int(base_value * level_factor)

def calculate_robbery_chance(
    base_chance: float, 
    attacker_luck: float, 
    victim_resistance: float,
    resist_divisor: float = 100.0,
    min_chance: float = 0.05,
    max_chance: float = 0.95
) -> float:
    
    mitigation = 1 / (1 + (victim_resistance / resist_divisor))
    final_chance = base_chance * attacker_luck * mitigation
    
    return max(min(max_chance, final_chance), min_chance)

def calculate_robbery_loss(
    potential_loss: float, 
    victim_resistance: float, 
    loss_divisor: float = 50.0
) -> float:
    loss_modifier = 1 / (1 + (victim_resistance / loss_divisor))
    return round(potential_loss * loss_modifier, 2)
