"""Add durable lifecycle timing columns to fishing events.

Revision ID: 20260802_0009
Revises: 20260802_0008
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260802_0009"
down_revision = "20260802_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("fishing_events")}
    additions = {
        "status": sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        "starts_at": sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        "ends_at": sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        "activated_at": sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        "deactivated_at": sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        "modifier_schema_version": sa.Column(
            "modifier_schema_version", sa.Integer(), nullable=False, server_default="2"
        ),
        "requires_review": sa.Column(
            "requires_review", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("fishing_events", column)
    indexes = {item["name"] for item in inspector.get_indexes("fishing_events")}
    if "ix_fishing_events_ends_at" not in indexes:
        op.create_index("ix_fishing_events_ends_at", "fishing_events", ["ends_at"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    indexes = {item["name"] for item in inspector.get_indexes("fishing_events")}
    if "ix_fishing_events_ends_at" in indexes:
        op.drop_index("ix_fishing_events_ends_at", table_name="fishing_events")
    for name in (
        "requires_review",
        "modifier_schema_version",
        "deactivated_at",
        "activated_at",
        "ends_at",
        "starts_at",
        "status",
    ):
        columns = {column["name"] for column in inspector.get_columns("fishing_events")}
        if name in columns:
            op.drop_column("fishing_events", name)
