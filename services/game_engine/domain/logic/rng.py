import random

def roll_loot(loot_table: list[dict], luck_modifier: float = 1.0):
    """
    Chooses an item from the loot table based on weights and a luck modifier.
    Args:
        loot_table (list[dict]): A list of items with their weights.
        luck_modifier (float): A modifier that affects the chance of rare items. E.g., 1.2 increases the chance by 20%.
    Returns:
        dict: The selected loot item.
    """
    # Логика изменения весов на основе удачи
    weighted_pool = []
    for item in loot_table:
        weight = item['weight']
        if item.get('rarity') == 'rare':
            weight *= luck_modifier
        weighted_pool.append(weight)
    
    return random.choices(loot_table, weights=weighted_pool, k=1)[0]