"""Store calculated points separately from the provider delta."""

from alembic import op
import sqlalchemy as sa


revision = "20260812_0036"
down_revision = "20260812_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "economy_operations",
        "points_delta",
        type_=sa.Numeric(30, 0),
        existing_type=sa.Integer(),
        existing_nullable=False,
        postgresql_using="points_delta::numeric",
    )
    op.add_column(
        "economy_operations",
        sa.Column("points_calculated", sa.Numeric(30, 0), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE economy_operations "
            "SET points_calculated = abs(points_delta) "
            "WHERE points_calculated IS NULL"
        )
    )
    op.alter_column(
        "economy_operations",
        "points_calculated",
        nullable=False,
        server_default=sa.text("0"),
    )


def downgrade() -> None:
    op.drop_column("economy_operations", "points_calculated")
    op.alter_column(
        "economy_operations",
        "points_delta",
        type_=sa.Integer(),
        existing_type=sa.Numeric(30, 0),
        existing_nullable=False,
        postgresql_using="points_delta::integer",
    )
