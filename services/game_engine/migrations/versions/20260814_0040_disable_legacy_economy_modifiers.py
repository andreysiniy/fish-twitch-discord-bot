"""Disable legacy player modifiers that attempted to change external economy."""

from alembic import op
import sqlalchemy as sa


revision = "20260814_0040"
down_revision = "20260814_0039"
branch_labels = None
depends_on = None

_LEGACY_STATS = (
    "sell_rate_bonus_pct",
    "buy_discount_pct",
    "points_flat_bonus",
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE player_modifiers "
            "SET is_enabled = FALSE, "
            "reason = CASE WHEN reason = '' THEN :reason ELSE reason || ' [legacy economy disabled]' END "
            "WHERE is_enabled = TRUE AND (scope = 'economy' OR stat_key IN :legacy_stats)"
        ).bindparams(sa.bindparam("legacy_stats", expanding=True)),
        {"reason": "Legacy external economy modifier archived", "legacy_stats": _LEGACY_STATS},
    )
    op.drop_constraint("ck_player_modifiers_scope", "player_modifiers", type_="check")
    op.create_check_constraint(
        "ck_player_modifiers_scope",
        "player_modifiers",
        "scope IN ('fishing','robbery','inventory','all')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_player_modifiers_scope", "player_modifiers", type_="check")
    op.create_check_constraint(
        "ck_player_modifiers_scope",
        "player_modifiers",
        "scope IN ('fishing','robbery','economy','inventory','all')",
    )
