"""Add loot-table stock, entry xp/message fields, and reward-pool link.

Revision ID: 20260802_0013
Revises: 20260802_0012
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260802_0013"
down_revision = "20260802_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())

    entries_columns = {
        column["name"] for column in inspector.get_columns("loot_table_entries")
    }
    if "xp_gain" not in entries_columns:
        op.add_column(
            "loot_table_entries",
            sa.Column("xp_gain", sa.Integer(), nullable=False, server_default="0"),
        )
    if "message" not in entries_columns:
        op.add_column("loot_table_entries", sa.Column("message", sa.String(), nullable=True))

    if "loot_table_entry_stock" not in inspector.get_table_names():
        op.create_table(
            "loot_table_entry_stock",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "loot_table_entry_id",
                sa.Integer(),
                sa.ForeignKey("loot_table_entries.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("remaining_quantity", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_loot_table_entry_stock_loot_table_entry_id",
            "loot_table_entry_stock",
            ["loot_table_entry_id"],
        )

    pool_columns = {
        column["name"] for column in inspector.get_columns("reward_pools")
    }
    if "item_loot_table_id" not in pool_columns:
        op.add_column(
            "reward_pools",
            sa.Column(
                "item_loot_table_id",
                sa.Integer(),
                sa.ForeignKey("loot_tables.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "loot_table_entry_stock" in inspector.get_table_names():
        op.drop_table("loot_table_entry_stock")
    for table, column in (("loot_table_entries", "message"), ("loot_table_entries", "xp_gain"), ("reward_pools", "item_loot_table_id")):
        columns = {c["name"] for c in inspector.get_columns(table)}
        if column in columns:
            op.drop_column(table, column)
