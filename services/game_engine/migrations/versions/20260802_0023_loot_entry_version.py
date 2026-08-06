"""Add versioned optimistic locking to loot table entries.

The Discord item-drop editor needs a version for concurrent-edit conflict
detection; loot_table_entries gained weight/xp/message editing and therefore
needs version + updated_at like every other versioned config row.

Revision ID: 20260802_0023
Revises: 20260802_0022
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260802_0023"
down_revision = "20260802_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("loot_table_entries")}
    if "version" not in columns:
        op.add_column(
            "loot_table_entries",
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        )
    if "updated_at" not in columns:
        op.add_column(
            "loot_table_entries",
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )


def downgrade() -> None:
    op.drop_column("loot_table_entries", "updated_at")
    op.drop_column("loot_table_entries", "version")
