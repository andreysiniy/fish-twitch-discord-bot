from decimal import Decimal
from typing import Any, Dict

from domain.item_schema import migrate_stat_key
from domain.logic.inventory_utils import find_equipped_rod
from domain.logic.mass import quantize_mass


def calculate_player_stats(user) -> Dict[str, Any]:
    """Resolve legacy stats for the non-resolver engine path.

    Uses the same v2 stat keys as the resolver: ``fish_luck_change_ratio`` etc.
    Legacy item effect keys are translated (including sign flips) by
    ``migrate_stat_key`` so old rods keep working until data migration runs.
    """
    equipped_rod = (
        find_equipped_rod(
            getattr(user, "equipped_items", None),
            getattr(user, "items", None),
        )
        or {}
    )
    resolved = {
        "luck_bonus": 0.0,
        "points_bonus": 0,
        "resist_bonus": 0.0,
        "xp_bonus_pct": 0.0,
        "good_catch_bonus": 0.0,
        "resolve_bad_catch": 0.0,
        "cd_bonus": 0.0,
        "item_drop_chance_add": 0.0,
        "item_rarity_luck_pct": 0.0,
    }
    for effect in equipped_rod.get("effects", []) or []:
        if effect.get("type") != "stat_add":
            continue
        try:
            stat, stat_value = migrate_stat_key(
                str(effect.get("stat") or ""), Decimal(str(effect.get("value", 0)))
            )
        except ValueError:
            continue
        value = float(stat_value)
        stat_name = stat.value
        if stat_name == "fish_luck_change_ratio":
            resolved["luck_bonus"] += value
        elif stat_name == "negative_fish_reward_change_ratio":
            resolved["resist_bonus"] += value
            resolved["resolve_bad_catch"] += value
        elif stat_name == "xp_gain_change_ratio":
            resolved["xp_bonus_pct"] += value
        elif stat_name == "positive_fish_reward_change_ratio":
            resolved["good_catch_bonus"] += value
        elif stat_name == "cooldown_change_ratio":
            resolved["cd_bonus"] += value
        elif stat_name == "item_drop_chance_add":
            resolved["item_drop_chance_add"] += value
        elif stat_name == "item_rarity_luck_pct":
            resolved["item_rarity_luck_pct"] += value

    return {
        "level": int(getattr(user, "level", 1) or 1),
        "xp": int(getattr(user, "xp", 0) or 0),
        "current_mass": quantize_mass(getattr(user, "current_mass", 0)),
        "total_fish_stat": int(getattr(user, "total_fish_stat", 0) or 0),
        "rod_name": equipped_rod.get("title", "No rod equipped"),
        **resolved,
        "total_mass_stat": quantize_mass(getattr(user, "total_mass_stat", 0)),
    }
