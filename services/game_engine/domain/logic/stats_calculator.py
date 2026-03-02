from typing import Any, Dict

from domain.logic.inventory_utils import find_equipped_rod


def calculate_player_stats(user) -> Dict[str, Any]:
    equipped_rod = find_equipped_rod(
        getattr(user, "inventory", {}) or {},
        getattr(user, "items", None)
    ) or {}
    rod_stats = equipped_rod.get("base_stats", {}) or {}

    return {
        "level": int(getattr(user, "level", 1) or 1),
        "xp": int(getattr(user, "xp", 0) or 0),
        "current_mass": float(getattr(user, "current_mass", 0.0) or 0.0),
        "total_fish_stat": int(getattr(user, "total_fish_stat", 0) or 0),
        "rod_name": equipped_rod.get("title", "No rod equipped"),
        "luck_bonus": float(rod_stats.get("luck_bonus", 0.0) or 0.0),
        "resist_bonus": float(rod_stats.get("resist_bonus", 0.0) or 0.0),
        "xp_bonus_pct": float(rod_stats.get("xp_bonus_pct", 0.0) or 0.0),
        "total_mass_stat": float(getattr(user, "total_mass_stat", 0.0) or 0.0),
    }
