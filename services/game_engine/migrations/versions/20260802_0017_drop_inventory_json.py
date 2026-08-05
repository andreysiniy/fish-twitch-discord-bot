"""Drop the legacy users_progress.inventory JSON column.

Revision ID: 20260802_0017
Revises: 20260802_0016

Inventory capacity lives in ``base_inventory_slots`` and equipment lives in
``equipped_items``; the JSON blob was a second source of truth. All runtime
readers have been switched to the normalized columns before this migration.
"""

from alembic import op
from sqlalchemy import inspect

revision = "20260802_0017"
down_revision = "20260802_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("users_progress")}
    if "inventory" in columns:
        op.drop_column("users_progress", "inventory")


def downgrade() -> None:
    op.add_column(
        "users_progress",
        __import__("sqlalchemy").Column(
            "inventory",
            __import__("sqlalchemy").JSONB(),
            nullable=False,
            server_default=__import__("sqlalchemy").text(
                "'{\"equipped_rod_slot\": null, \"max_slots\": 20}'"
            ),
        ),
    )
