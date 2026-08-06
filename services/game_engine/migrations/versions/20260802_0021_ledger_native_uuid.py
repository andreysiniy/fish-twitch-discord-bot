"""Convert fishing ledger primary keys to native PostgreSQL UUID.

FishingCast, FishingCastItemDrop and FishingRulesetSnapshot ids move from
String (uuid4 text) to native UUID columns. All existing values are already
UUID-formatted, so the cast is a straight ``USING id::uuid`` conversion and
never re-rolls RNG or rewrites rows.

Revision ID: 20260802_0021
Revises: 20260802_0020
"""

from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "20260802_0021"
down_revision = "20260802_0020"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    bind = op.get_bind()
    # Type changes require dropping FKs that reference the converted columns.
    for table, referenced in (
        ("fishing_casts", "fishing_ruleset_snapshots"),
        ("fishing_cast_item_drops", "fishing_casts"),
    ):
        inspector = inspect(bind)
        for fk in inspector.get_foreign_keys(table):
            if fk.get("referred_table") == referenced:
                op.drop_constraint(fk["name"], table, type_="foreignkey")

    op.alter_column(
        "fishing_ruleset_snapshots",
        "id",
        type_=_UUID,
        postgresql_using="id::uuid",
    )
    op.alter_column(
        "fishing_casts",
        "id",
        type_=_UUID,
        postgresql_using="id::uuid",
    )
    op.alter_column(
        "fishing_casts",
        "ruleset_snapshot_id",
        type_=_UUID,
        postgresql_using="ruleset_snapshot_id::uuid",
    )
    op.alter_column(
        "fishing_cast_item_drops",
        "id",
        type_=_UUID,
        postgresql_using="id::uuid",
    )
    op.alter_column(
        "fishing_cast_item_drops",
        "cast_id",
        type_=_UUID,
        postgresql_using="cast_id::uuid",
    )
    # Restore the dropped FKs with matching types.
    op.create_foreign_key(
        "fk_fishing_casts_ruleset_snapshot",
        "fishing_casts",
        "fishing_ruleset_snapshots",
        ["ruleset_snapshot_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_fishing_cast_item_drops_cast_channel",
        "fishing_cast_item_drops",
        "fishing_casts",
        ["cast_id", "channel_id"],
        ["id", "channel_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    for table, column in (
        ("fishing_cast_item_drops", "cast_id"),
        ("fishing_cast_item_drops", "id"),
        ("fishing_casts", "ruleset_snapshot_id"),
        ("fishing_casts", "id"),
        ("fishing_ruleset_snapshots", "id"),
    ):
        op.alter_column(table, column, type_=postgresql.VARCHAR())
