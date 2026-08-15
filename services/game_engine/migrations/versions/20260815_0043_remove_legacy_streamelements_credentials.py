"""Drop legacy channel-level StreamElements credentials after preflight."""

import sqlalchemy as sa
from alembic import op


revision = "20260815_0043"
down_revision = "20260815_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    missing = bind.execute(
        sa.text(
            "SELECT c.id FROM channels c "
            "WHERE (c.se_token IS NOT NULL OR c.se_channel_id IS NOT NULL) "
            "AND NOT EXISTS (SELECT 1 FROM channel_integrations i "
            "WHERE i.channel_id = c.id AND i.provider = 'streamelements') "
            "ORDER BY c.id"
        )
    ).scalars().all()
    if missing:
        raise RuntimeError(
            "Legacy StreamElements credentials are not migrated for channel IDs: "
            + ", ".join(str(value) for value in missing)
        )
    op.drop_column("channels", "se_token")
    op.drop_column("channels", "se_channel_id")


def downgrade() -> None:
    # The old credential values were intentionally not retained.  Restore
    # nullable columns only so an emergency downgrade can complete safely.
    op.add_column("channels", sa.Column("se_token", sa.String(), nullable=True))
    op.add_column("channels", sa.Column("se_channel_id", sa.String(), nullable=True))
