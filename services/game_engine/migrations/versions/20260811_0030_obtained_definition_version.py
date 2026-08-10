"""Make inventory definition version semantics explicit."""

import sqlalchemy as sa
from alembic import op

revision = "20260811_0030"
down_revision = "20260811_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inventory_items",
        sa.Column("obtained_definition_version", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE inventory_items SET obtained_definition_version = definition_version "
        "WHERE obtained_definition_version IS NULL"
    )
    op.alter_column("inventory_items", "obtained_definition_version", nullable=False)
    op.create_check_constraint(
        "ck_inventory_items_obtained_definition_version_positive",
        "inventory_items",
        "obtained_definition_version >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_inventory_items_obtained_definition_version_positive",
        "inventory_items",
        type_="check",
    )
    op.drop_column("inventory_items", "obtained_definition_version")
