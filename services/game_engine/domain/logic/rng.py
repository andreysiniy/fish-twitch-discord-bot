import random

RARITY_RANK = {
    "common": 0,
    "rare": 1,
    "epic": 2,
    "legendary": 3,
}

def roll_loot(loot_table: list[dict], luck_modifier: float = 1.0):
    """
    Chooses an item from the loot table based on weights and a luck modifier.
    Args:
        loot_table (list[dict]): A list of items with their weights.
        luck_modifier (float): A multiplier that shifts weight toward higher rarities.
    Returns:
        dict: The selected loot item.
    """
    weighted_pool = []
    for item in loot_table:
        weight = item['weight']
        rarity_rank = RARITY_RANK.get(str(item.get("rarity", "common")).lower(), 0)
        safe_luck = max(float(luck_modifier), 0.05)
        weight *= safe_luck**rarity_rank
        weighted_pool.append(weight)
    
    return random.choices(loot_table, weights=weighted_pool, k=1)[0]

def calculate_chance(chance: float) -> bool:
    return random.random() < chance

def is_russian_roulette_hit(bullets: int, chambers: int) -> bool:
    if chambers <= 0:
        return False
    return calculate_chance(bullets / chambers)
