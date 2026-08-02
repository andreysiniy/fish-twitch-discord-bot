"""Add Discord identity and versioned administration state."""

from alembic import op
from sqlalchemy import inspect

from infrastructure.database import Base
import infrastructure.models  # noqa: F401


revision = "20260802_0002"
down_revision = "20260802_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    _add_column_if_missing(
        inspector,
        "channels",
        "config_version",
        "ALTER TABLE channels ADD COLUMN config_version INTEGER NOT NULL DEFAULT 1",
    )
    _add_column_if_missing(
        inspector,
        "channels",
        "config_updated_at",
        "ALTER TABLE channels ADD COLUMN config_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    )
    _add_column_if_missing(
        inspector,
        "reward_pools",
        "version",
        "ALTER TABLE reward_pools ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
    )
    _add_column_if_missing(
        inspector,
        "reward_pools",
        "updated_at",
        "ALTER TABLE reward_pools ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    )
    _add_column_if_missing(
        inspector,
        "fishing_events",
        "version",
        "ALTER TABLE fishing_events ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
    )
    _add_column_if_missing(
        inspector,
        "fishing_events",
        "created_at",
        "ALTER TABLE fishing_events ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    )
    _add_column_if_missing(
        inspector,
        "fishing_events",
        "updated_at",
        "ALTER TABLE fishing_events ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
    )

    for table_name in (
        "discord_account_links",
        "discord_guild_bindings",
        "admin_audit_log",
        "idempotency_records",
    ):
        Base.metadata.tables[table_name].create(bind=bind, checkfirst=True)

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        UPDATE reward_pools
        SET rewards_data = COALESCE((
            SELECT jsonb_agg(
                CASE
                    WHEN reward ? 'reward_id' THEN reward
                    ELSE jsonb_set(reward, '{reward_id}', to_jsonb(gen_random_uuid()::text))
                END
                ORDER BY ordinal
            )
            FROM jsonb_array_elements(COALESCE(rewards_data, '[]'::jsonb))
                WITH ORDINALITY AS entries(reward, ordinal)
        ), '[]'::jsonb)
        """
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_table("admin_audit_log")
    op.drop_table("discord_guild_bindings")
    op.drop_table("discord_account_links")
    op.drop_column("fishing_events", "updated_at")
    op.drop_column("fishing_events", "created_at")
    op.drop_column("fishing_events", "version")
    op.drop_column("reward_pools", "updated_at")
    op.drop_column("reward_pools", "version")
    op.drop_column("channels", "config_updated_at")
    op.drop_column("channels", "config_version")


def _add_column_if_missing(inspector, table: str, column: str, statement: str) -> None:
    if column not in {item["name"] for item in inspector.get_columns(table)}:
        op.execute(statement)
