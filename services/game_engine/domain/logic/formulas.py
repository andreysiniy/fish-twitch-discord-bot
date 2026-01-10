def calculate_xp_required(level: int) -> int:
    """
    Calculates the XP required to reach the next level.
    For example, using a simple formula: XP = 100 * (level ^ 1.5)
    """
    return int(100 * (level ** 1.5))

def is_level_up(current_xp: int, current_level: int) -> bool:
    return current_xp >= calculate_xp_required(current_level)