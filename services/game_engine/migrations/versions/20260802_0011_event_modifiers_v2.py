"""Migrate legacy event modifiers (v1) to the v2 human-percent schema.

Revision ID: 20260802_0011
Revises: 20260802_0010
"""

import json
from decimal import Decimal, ROUND_HALF_UP

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260802_0011"
down_revision = "20260802_0010"
branch_labels = None
depends_on = None

# Safe caps for v2 human-percent values; anything beyond requires owner review.
POSITIVE_REWARD_SAFE_CAP = Decimal("200")
XP_SAFE_CAP = Decimal("200")
LUCK_SAFE_CAP = Decimal("200")


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "fishing_events" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("fishing_events")}
    if "modifiers" not in columns:
        return
    if "modifiers_history" not in columns:
        op.add_column(
            "fishing_events",
            sa.Column(
                "modifiers_history",
                sa.dialects.postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )

    bind = op.get_bind()
    rows = bind.exec_driver_sql(
        "SELECT id, modifiers, is_active FROM fishing_events"
    ).fetchall()
    legacy_columns = {"luck_mult", "xp_mult", "cd_reduction", "bonus_mass"}

    for row in rows:
        event_id, modifiers, is_active = row[0], row[1], row[2]
        if not modifiers:
            continue
        try:
            payload = dict(modifiers)
        except (TypeError, ValueError):
            continue
        if payload.get("schema_version") == 2:
            continue
        if not legacy_columns.intersection(payload.keys()):
            continue

        legacy_payload = dict(payload)
        converted = _convert_legacy_to_v2(payload)
        requires_review = _requires_review(converted)

        # Stop an active event that became unsafe rather than silently running it.
        final_is_active = bool(is_active) and not requires_review
        # Preserve unsafe originals for owner review; owner confirmation re-enables.
        historical = {"legacy_modifiers": legacy_payload, "converted_v2": converted}
        bind.exec_driver_sql(
            "UPDATE fishing_events SET modifiers = %s, modifier_schema_version = 2, "
            "requires_review = %s, is_active = %s, "
            "modifiers_history = COALESCE(modifiers_history, '[]'::jsonb) || %s::jsonb "
            "WHERE id = %s",
            (
                json.dumps(converted, ensure_ascii=False),
                requires_review,
                final_is_active,
                json.dumps([historical], ensure_ascii=False),
                event_id,
            ),
        )


def downgrade() -> None:
    # v2 → legacy is intentionally not supported: it would corrupt review flags
    # and silently reinterpret percentages. Downgrade only via backup restore.
    pass


def _convert_legacy_to_v2(payload: dict) -> dict:
    luck = Decimal(str(payload.get("luck_mult", 1)))
    xp = Decimal(str(payload.get("xp_mult", 1)))
    cd = Decimal(str(payload.get("cd_reduction", 0)))
    bonus = Decimal(str(payload.get("bonus_mass", 0)))

    def pct(value: Decimal) -> str:
        return str((value * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    negative_reward = Decimal("0")
    if bonus > 0:
        negative_reward = Decimal("1") / (Decimal("1") + bonus) - Decimal("1")

    converted = {
        "schema_version": 2,
        "fish_luck_change_percent": pct(luck - Decimal("1")),
        "xp_gain_change_percent": pct(xp - Decimal("1")),
        "cooldown_change_percent": pct(-cd),
        "positive_fish_reward_change_percent": pct(bonus),
        "negative_fish_reward_change_percent": pct(negative_reward),
    }
    # Drop zero-value keys for determinism; keep the rest as v2.
    return {key: value for key, value in converted.items() if value not in ("0", "-0.00", "0.00")}


def _requires_review(payload: dict) -> bool:
    def exceeds(key: str, cap: Decimal) -> bool:
        raw = payload.get(key)
        if raw is None:
            return False
        try:
            return abs(Decimal(str(raw))) > cap
        except Exception:
            return False

    return any(
        [
            exceeds("positive_fish_reward_change_percent", POSITIVE_REWARD_SAFE_CAP),
            exceeds("xp_gain_change_percent", XP_SAFE_CAP),
            exceeds("fish_luck_change_percent", LUCK_SAFE_CAP),
        ]
    )
