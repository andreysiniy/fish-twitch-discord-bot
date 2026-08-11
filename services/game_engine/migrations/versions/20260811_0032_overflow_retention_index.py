"""Index parked overflow rows for the 24-hour retention sweep.

The retention worker removes only rows that are still parked and older than
the mailbox TTL.  A composite index keeps that periodic cleanup bounded as
the historical claimed/revoked ledger grows.
"""

from alembic import op

revision = "20260811_0032"
down_revision = "20260811_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_inventory_overflow_items_status_created_at",
        "inventory_overflow_items",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_overflow_items_status_created_at",
        table_name="inventory_overflow_items",
    )
