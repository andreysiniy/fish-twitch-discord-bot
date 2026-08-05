"""Add targeted indexes for outbox polling and player modifier lookups.

Revision ID: 20260802_0018
Revises: 20260802_0017
"""

from alembic import op
from sqlalchemy import inspect, text

revision = "20260802_0018"
down_revision = "20260802_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    existing = {
        index["name"]
        for index in inspector.get_indexes("outbox_events")
    }
    if "ix_outbox_pending_due" not in existing:
        op.create_index(
            "ix_outbox_pending_due",
            "outbox_events",
            ["next_attempt_at", "created_at"],
            postgresql_where=text("state = 'pending'"),
        )
    if "ix_outbox_processing_lease" not in existing:
        op.create_index(
            "ix_outbox_processing_lease",
            "outbox_events",
            ["lease_expires_at", "created_at"],
            postgresql_where=text("state = 'processing'"),
        )

    pm_existing = {
        index["name"]
        for index in inspector.get_indexes("player_modifiers")
    }
    if "ix_player_modifiers_user" not in pm_existing:
        op.create_index(
            "ix_player_modifiers_user", "player_modifiers", ["user_progress_id"]
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes("outbox_events")}
    if "ix_outbox_pending_due" in existing:
        op.drop_index("ix_outbox_pending_due", table_name="outbox_events")
    if "ix_outbox_processing_lease" in existing:
        op.drop_index("ix_outbox_processing_lease", table_name="outbox_events")
    pm_existing = {
        index["name"]
        for index in inspector.get_indexes("player_modifiers")
    }
    if "ix_player_modifiers_user" in pm_existing:
        op.drop_index("ix_player_modifiers_user", table_name="player_modifiers")
