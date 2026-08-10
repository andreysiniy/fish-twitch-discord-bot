"""Add optimistic versions for reconciliation actions."""

import sqlalchemy as sa
from alembic import op

revision = "20260811_0029"
down_revision = "20260806_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "economy_operations",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "outbox_events",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_check_constraint(
        "ck_economy_operations_version_positive",
        "economy_operations",
        "version >= 1",
    )
    op.create_check_constraint(
        "ck_outbox_events_version_positive",
        "outbox_events",
        "version >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_outbox_events_version_positive", "outbox_events", type_="check"
    )
    op.drop_constraint(
        "ck_economy_operations_version_positive", "economy_operations", type_="check"
    )
    op.drop_column("outbox_events", "version")
    op.drop_column("economy_operations", "version")
