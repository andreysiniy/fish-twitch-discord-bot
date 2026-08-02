"""Remove migrated legacy item columns.

Revision ID: 20260802_0006
Revises: 20260802_0005
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260802_0006"
down_revision = "20260802_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("item_definitions")}
    for name in ("durability", "base_stats"):
        if name in columns:
            op.drop_column("item_definitions", name)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("item_definitions")}
    if "durability" not in columns:
        op.add_column(
            "item_definitions",
            sa.Column("durability", sa.Integer(), nullable=True),
        )
    if "base_stats" not in columns:
        op.add_column(
            "item_definitions",
            sa.Column(
                "base_stats",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
