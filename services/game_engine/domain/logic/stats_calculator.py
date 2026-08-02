from typing import Any, Dict

from domain.logic.inventory_utils import find_equipped_rod
from domain.logic.mass import quantize_mass


def calculate_player_stats(user) -> Dict[str, Any]:
    equipped_rod = (
        find_equipped_rod(getattr(user, "inventory", {}) or {}, getattr(user, "items", None)) or {}
    )
    resolved = {
        "luck_bonus": 0.0,
        "points_bonus": 0,
        "resist_bonus": 0.0,
        "xp_bonus_pct": 0.0,
    }
    stat_mapping = {
        "loot_luck_pct": "luck_bonus",
        "points_flat_bonus": "points_bonus",
        "negative_mass_reduction_pct": "resist_bonus",
        "xp_gain_bonus_pct": "xp_bonus_pct",
    }
    for effect in equipped_rod.get("effects", []) or []:
        target = stat_mapping.get(str(effect.get("stat") or ""))
        if effect.get("type") == "stat_add" and target:
            resolved[target] += float(effect.get("value", 0))

    return {
        "level": int(getattr(user, "level", 1) or 1),
        "xp": int(getattr(user, "xp", 0) or 0),
        "current_mass": quantize_mass(getattr(user, "current_mass", 0)),
        "total_fish_stat": int(getattr(user, "total_fish_stat", 0) or 0),
        "rod_name": equipped_rod.get("title", "No rod equipped"),
        **resolved,
        "total_mass_stat": quantize_mass(getattr(user, "total_mass_stat", 0)),
    }
