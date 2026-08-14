"""Make spread pricing the only public economy model."""

from alembic import op
import sqlalchemy as sa


revision = "20260814_0039"
down_revision = "20260814_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE channel_economy_settings "
            "SET sell_points_per_kg = buy_points_per_kg "
            "WHERE pricing_mode = 'single_rate'"
        )
    )
    op.drop_constraint(
        "ck_economy_settings_pricing_mode",
        "channel_economy_settings",
        type_="check",
    )
    op.drop_column("channel_economy_settings", "pricing_mode")


def downgrade() -> None:
    op.add_column(
        "channel_economy_settings",
        sa.Column("pricing_mode", sa.String(), nullable=False, server_default="spread"),
    )
    op.create_check_constraint(
        "ck_economy_settings_pricing_mode",
        "channel_economy_settings",
        "pricing_mode IN ('single_rate','spread')",
    )
