"""Report and safely backfill known Twitch bootstrap channels."""

import logging
import os

import sqlalchemy as sa
from alembic import op


revision = "20260815_0044"
down_revision = "20260815_0043"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    bind = op.get_bind()
    raw = os.getenv("BOOTSTRAP_CHANNELS") or ""
    unknown: list[str] = []
    for login in sorted({value.strip().lower() for value in raw.split(",") if value.strip()}):
        channel_id = bind.execute(
            sa.text(
                "SELECT id FROM channels "
                "WHERE lower(name) = :login OR lower(twitch_id) = :login "
                "ORDER BY id LIMIT 1"
            ),
            {"login": login},
        ).scalar()
        if channel_id is None:
            unknown.append(login)
            continue
        bind.execute(
            sa.text(
                "UPDATE channels SET twitch_bot_enabled = true, "
                "bot_membership_updated_at = now() WHERE id = :channel_id"
            ),
            {"channel_id": channel_id},
        )
    if unknown:
        logger.warning(
            "Twitch membership bootstrap preflight found unknown logins: %s",
            ", ".join(unknown),
        )


def downgrade() -> None:
    # This data backfill is intentionally not reversed: desired membership is
    # operator-controlled state and a downgrade must not disable channels.
    pass
