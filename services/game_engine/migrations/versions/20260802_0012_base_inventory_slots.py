"""Add users_progress.base_inventory_slots and backfill from JSON inventory.

Revision ID: 20260802_0012
Revises: 20260802_0011
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260802_0012"
down_revision = "20260802_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("users_progress")}
    if "base_inventory_slots" not in columns:
        op.add_column(
            "users_progress",
            sa.Column("base_inventory_slots", sa.Integer(), nullable=False, server_default="20"),
        )
    # Backfill from the legacy JSON field where set.
    op.execute(
        "UPDATE users_progress "
        "SET base_inventory_slots = "
        "CASE WHEN (inventory->>'max_slots') ~ '^[0-9]+$' "
        "THEN GREATEST((inventory->>'max_slots')::integer, 1) "
        "ELSE base_inventory_slots END"
    )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("users_progress")}
    if "base_inventory_slots" in columns:
        op.drop_column("users_progress", "base_inventory_slots")
