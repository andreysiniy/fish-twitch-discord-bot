"""Remove unfinished item economy flags.

Revision ID: 20260802_0005
Revises: 20260802_0004
"""

from alembic import op
import sqlalchemy as sa


revision = "20260802_0005"
down_revision = "20260802_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("item_definitions")}
    for name in ("sell_value", "is_sellable", "is_tradeable"):
        if name in columns:
            op.drop_column("item_definitions", name)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("item_definitions")}
    if "sell_value" not in columns:
        op.add_column(
            "item_definitions",
            sa.Column("sell_value", sa.Numeric(18, 2), nullable=True),
        )
    if "is_sellable" not in columns:
        op.add_column(
            "item_definitions",
            sa.Column(
                "is_sellable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )
    if "is_tradeable" not in columns:
        op.add_column(
            "item_definitions",
            sa.Column(
                "is_tradeable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )
