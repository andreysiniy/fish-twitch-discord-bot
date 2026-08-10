"""Add durable inventory overflow storage for full-inventory item drops.

A full inventory must never lose a finite-stock drop (plan section 10): the
fishing delivery parks the item in ``inventory_overflow_items`` and counts the
drop as delivered until a moderator claims it back. Composite FKs keep the rows
tenant-safe, mirroring ``inventory_items``.

Revision ID: 20260806_0028
Revises: 20260806_0027
"""

import sqlalchemy as sa
from alembic import op

revision = "20260806_0028"
down_revision = "20260806_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_overflow_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("item_definition_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "source_type",
            sa.String(),
            nullable=False,
            server_default=sa.text("'fishing_cast'"),
        ),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'parked'")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id", "channel_id"],
            ["users_progress.id", "users_progress.channel_id"],
            name="fk_inventory_overflow_items_user_channel",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["item_definition_id", "channel_id"],
            ["item_definitions.id", "item_definitions.channel_id"],
            name="fk_inventory_overflow_items_item_channel",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_inventory_overflow_items_quantity_positive"),
        sa.CheckConstraint(
            "status IN ('parked','claimed','revoked')",
            name="ck_inventory_overflow_items_status",
        ),
        sa.CheckConstraint(
            "source_type IN ('fishing_cast','lootbox')",
            name="ck_inventory_overflow_items_source_type",
        ),
        sa.CheckConstraint("version >= 1", name="ck_inventory_overflow_items_version_positive"),
    )
    op.create_index(
        "ix_inventory_overflow_items_channel_id",
        "inventory_overflow_items",
        ["channel_id"],
    )
    op.create_index(
        "ix_inventory_overflow_items_item_definition_id",
        "inventory_overflow_items",
        ["item_definition_id"],
    )
    op.create_index(
        "ix_inventory_overflow_items_user",
        "inventory_overflow_items",
        ["user_id"],
    )
    op.create_index(
        "ix_inventory_overflow_items_status",
        "inventory_overflow_items",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_overflow_items_status", table_name="inventory_overflow_items")
    op.drop_index("ix_inventory_overflow_items_user", table_name="inventory_overflow_items")
    op.drop_index(
        "ix_inventory_overflow_items_item_definition_id",
        table_name="inventory_overflow_items",
    )
    op.drop_index(
        "ix_inventory_overflow_items_channel_id",
        table_name="inventory_overflow_items",
    )
    op.drop_table("inventory_overflow_items")
