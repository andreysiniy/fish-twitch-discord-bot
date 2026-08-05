"""Add the idempotent daily fishing-stats aggregate table.

Revision ID: 20260802_0014
Revises: 20260802_0013
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260802_0014"
down_revision = "20260802_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if "fishing_stats_daily" not in inspector.get_table_names():
        op.create_table(
            "fishing_stats_daily",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("day", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
            ),
            sa.Column("location_id", sa.String(), nullable=True),
            sa.Column("event_id", sa.Integer(), nullable=True),
            sa.Column("reward_type", sa.String(), nullable=True),
            sa.Column("item_definition_id", sa.Integer(), nullable=True),
            sa.Column("casts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unique_players", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "mass_positive", sa.Numeric(18, 2), nullable=False, server_default="0"
            ),
            sa.Column(
                "mass_negative", sa.Numeric(18, 2), nullable=False, server_default="0"
            ),
            sa.Column("xp_gained", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "item_drop_expected", sa.Numeric(18, 2), nullable=False, server_default="0"
            ),
            sa.Column("item_drop_actual", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "day",
                "channel_id",
                "location_id",
                "event_id",
                "reward_type",
                "item_definition_id",
                name="uq_fishing_stats_daily_bucket",
            ),
        )
        op.create_index(
            "ix_fishing_stats_daily_channel_day",
            "fishing_stats_daily",
            ["channel_id", "day"],
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "fishing_stats_daily" in inspector.get_table_names():
        op.drop_table("fishing_stats_daily")
