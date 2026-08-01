from typing import Any, Dict

from domain.logic.inventory_utils import find_equipped_rod
from domain.logic.mass import quantize_mass
from domain.schemas.rpg import ItemStats


def calculate_player_stats(user) -> Dict[str, Any]:
    equipped_rod = (
        find_equipped_rod(getattr(user, "inventory", {}) or {}, getattr(user, "items", None)) or {}
    )
    rod_stats = equipped_rod.get("base_stats", {}) or {}
    validated_stats = ItemStats.model_validate(rod_stats)

    return {
        "level": int(getattr(user, "level", 1) or 1),
        "xp": int(getattr(user, "xp", 0) or 0),
        "current_mass": quantize_mass(getattr(user, "current_mass", 0)),
        "total_fish_stat": int(getattr(user, "total_fish_stat", 0) or 0),
        "rod_name": equipped_rod.get("title", "No rod equipped"),
        "luck_bonus": validated_stats.luck_bonus,
        "points_bonus": validated_stats.points_bonus,
        "resist_bonus": validated_stats.resist_bonus,
        "xp_bonus_pct": validated_stats.xp_bonus_pct,
        "total_mass_stat": quantize_mass(getattr(user, "total_mass_stat", 0)),
    }
