"""Remove the unsupported loot-entry rarity filter after a preflight."""

from alembic import op
import sqlalchemy as sa


revision = "20260814_0038"
down_revision = "20260812_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    remaining = bind.execute(
        sa.text(
            "SELECT count(*) FROM loot_table_entries "
            "WHERE rarity_filter IS NOT NULL AND btrim(rarity_filter) <> ''"
        )
    ).scalar_one()
    if remaining:
        raise RuntimeError(
            "rarity_filter preflight failed: "
            f"{remaining} loot entries still contain values; export and review them before migration"
        )
    op.drop_column("loot_table_entries", "rarity_filter")


def downgrade() -> None:
    op.add_column("loot_table_entries", sa.Column("rarity_filter", sa.String(), nullable=True))
