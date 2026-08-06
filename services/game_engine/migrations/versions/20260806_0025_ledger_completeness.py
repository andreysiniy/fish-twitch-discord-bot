"""Ledger completeness: failed rows, drop sub-flags, NULLS NOT DISTINCT daily.

Closes the remaining cast-journal gaps from the compliance review:

- ``fishing_casts.error_message`` stores the failure detail for failed rows;
- fine-grained item-drop outcome columns (gate/selection/stock/grant) record
  each stage separately so a full-inventory grant failure is not confused
  with a failed gate roll;
- the daily-stats bucket unique index uses ``NULLS NOT DISTINCT`` so parallel
  rebuilds cannot create duplicate buckets when dimensions are NULL.

Revision ID: 20260806_0025
Revises: 20260806_0024
"""

from alembic import op
import sqlalchemy as sa

revision = "20260806_0025"
down_revision = "20260806_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fishing_casts",
        sa.Column("error_message", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "fishing_casts",
        sa.Column("item_drop_gate_success", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "fishing_casts",
        sa.Column("item_drop_selection_success", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "fishing_casts",
        sa.Column("item_drop_stock_reserved", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "fishing_casts",
        sa.Column("item_drop_grant_success", sa.Boolean(), nullable=True),
    )
    op.drop_constraint(
        "uq_fishing_stats_daily_bucket",
        "fishing_stats_daily",
        type_="unique",
    )
    op.create_index(
        "uq_fishing_stats_daily_bucket",
        "fishing_stats_daily",
        [
            "day",
            "channel_id",
            "location_id",
            "event_id",
            "reward_type",
            "item_definition_id",
        ],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_fishing_stats_daily_bucket",
        table_name="fishing_stats_daily",
    )
    op.create_unique_constraint(
        "uq_fishing_stats_daily_bucket",
        "fishing_stats_daily",
        [
            "day",
            "channel_id",
            "location_id",
            "event_id",
            "reward_type",
            "item_definition_id",
        ],
    )
    op.drop_column("fishing_casts", "item_drop_grant_success")
    op.drop_column("fishing_casts", "item_drop_stock_reserved")
    op.drop_column("fishing_casts", "item_drop_selection_success")
    op.drop_column("fishing_casts", "item_drop_gate_success")
    op.drop_column("fishing_casts", "error_message")
