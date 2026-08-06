"""Migrate stat keys and values to the modifiers v2 schema.

Renames resolver stat keys used by player modifiers and item effect JSON:

- loot_luck_pct            -> fish_luck_change_ratio
- positive_mass_bonus_pct  -> positive_fish_reward_change_ratio
- negative_mass_reduction_pct -> negative_fish_reward_change_ratio  (sign flip)
- xp_gain_bonus_pct        -> xp_gain_change_ratio
- cooldown_reduction_pct   -> cooldown_change_ratio               (sign flip)

Legacy ``bonus_mass = 5`` semantics are preserved by the earlier event
migration; this revision only rewrites stored modifier keys. Unknown legacy
keys abort the migration with a preflight report instead of being dropped.

Revision ID: 20260802_0019
Revises: 20260802_0018
"""

import json
from decimal import Decimal

from alembic import op
from sqlalchemy import text

revision = "20260802_0019"
down_revision = "20260802_0018"
branch_labels = None
depends_on = None

_KEY_MIGRATION = {
    "loot_luck_pct": "fish_luck_change_ratio",
    "positive_mass_bonus_pct": "positive_fish_reward_change_ratio",
    "negative_mass_reduction_pct": "negative_fish_reward_change_ratio",
    "xp_gain_bonus_pct": "xp_gain_change_ratio",
    "cooldown_reduction_pct": "cooldown_change_ratio",
}
_SIGN_FLIP_KEYS = {"negative_mass_reduction_pct", "cooldown_reduction_pct"}


def _as_list(effects) -> list:
    """Normalize a JSONB value from the driver into a Python list."""
    if effects is None:
        return []
    if isinstance(effects, str):
        return json.loads(effects)
    if isinstance(effects, list):
        return effects
    return [effects]
_ALLOWED_KEYS = {
    "fish_luck_change_ratio",
    "positive_fish_reward_change_ratio",
    "negative_fish_reward_change_ratio",
    "xp_gain_change_ratio",
    "cooldown_change_ratio",
    "points_flat_bonus",
    "item_drop_chance_add",
    "item_rarity_luck_pct",
    "empty_catch_reroll_chance_pct",
    "robbery_protection_pct",
    "robbery_evasion_pct",
    "protected_mass_flat",
    "robbery_counter_chance_pct",
    "robbery_attack_chance_add",
    "robbery_amount_bonus_pct",
    "inventory_slots_add",
    "sell_rate_bonus_pct",
    "buy_discount_pct",
}


def _migrate_effects(effects) -> list:
    migrated = []
    for effect in effects or []:
        if not isinstance(effect, dict):
            migrated.append(effect)
            continue
        stat = str(effect.get("stat") or "")
        if stat in _KEY_MIGRATION:
            new_stat = _KEY_MIGRATION[stat]
            try:
                value = Decimal(str(effect.get("value", 0)))
            except Exception as exc:  # pragma: no cover - defensive
                raise ValueError(
                    f"Non-numeric value {effect.get('value')!r} for stat {stat!r}"
                ) from exc
            if stat in _SIGN_FLIP_KEYS:
                value = -value
            effect = {**effect, "stat": new_stat, "value": str(value)}
        elif stat and stat not in _ALLOWED_KEYS:
            raise ValueError(
                f"Unknown legacy stat key {stat!r} in item effects; "
                "aborting migration to avoid data loss"
            )
        migrated.append(effect)
    return migrated


def upgrade() -> None:
    bind = op.get_bind()

    # --- preflight: unknown player modifier stat keys abort ---
    known = sorted(_ALLOWED_KEYS | set(_KEY_MIGRATION))
    unknown_modifier_keys = [
        row[0]
        for row in bind.execute(
            text("SELECT DISTINCT stat_key FROM player_modifiers")
        ).fetchall()
        if row[0] not in known
    ]
    if unknown_modifier_keys:
        raise RuntimeError(
            "Cannot migrate player_modifiers with unknown stat keys: "
            + ", ".join(sorted(unknown_modifier_keys))
        )

    # --- preflight: unknown item effect stat keys abort ---
    effect_rows = bind.execute(
        text(
            "SELECT id, effects FROM item_definitions "
            "WHERE jsonb_typeof(effects) = 'array'"
        )
    ).fetchall()
    for _, effects in effect_rows:
        _migrate_effects(_as_list(effects))  # raises on unknown keys

    # --- rewrite player_modifiers.stat_key (and flip sign where needed) ---
    for old_key, new_key in _KEY_MIGRATION.items():
        if old_key in _SIGN_FLIP_KEYS:
            bind.execute(
                text(
                    "UPDATE player_modifiers SET stat_key = :new_key, value = -value "
                    "WHERE stat_key = :old_key"
                ),
                {"new_key": new_key, "old_key": old_key},
            )
        else:
            bind.execute(
                text(
                    "UPDATE player_modifiers SET stat_key = :new_key "
                    "WHERE stat_key = :old_key"
                ),
                {"new_key": new_key, "old_key": old_key},
            )

    # --- rewrite item_definitions.effects JSONB ---
    for item_id, effects in effect_rows:
        migrated = _migrate_effects(_as_list(effects))
        bind.execute(
            text("UPDATE item_definitions SET effects = :effects WHERE id = :id"),
            {"effects": json.dumps(migrated), "id": item_id},
        )


def downgrade() -> None:
    """Best-effort reverse rename; sign flips are restored too."""
    reverse = {new: old for old, new in _KEY_MIGRATION.items()}
    bind = op.get_bind()
    for new_key, old_key in reverse.items():
        if old_key in _SIGN_FLIP_KEYS:
            bind.execute(
                text(
                    "UPDATE player_modifiers SET stat_key = :old_key, value = -value "
                    "WHERE stat_key = :new_key"
                ),
                {"old_key": old_key, "new_key": new_key},
            )
        else:
            bind.execute(
                text(
                    "UPDATE player_modifiers SET stat_key = :old_key "
                    "WHERE stat_key = :new_key"
                ),
                {"old_key": old_key, "new_key": new_key},
            )
    for item_id, effects in bind.execute(
        text(
            "SELECT id, effects FROM item_definitions "
            "WHERE jsonb_typeof(effects) = 'array'"
        )
    ).fetchall():
        migrated = _migrate_effects(_as_list(effects))
        migrated = [
            {
                **effect,
                "stat": reverse.get(str(effect.get("stat")), effect.get("stat")),
                "value": str(-Decimal(str(effect["value"])))
                if reverse.get(str(effect.get("stat"))) in _SIGN_FLIP_KEYS
                else effect.get("value"),
            }
            if isinstance(effect, dict)
            else effect
            for effect in migrated
        ]
        bind.execute(
            text("UPDATE item_definitions SET effects = :effects WHERE id = :id"),
            {"effects": json.dumps(migrated), "id": item_id},
        )
