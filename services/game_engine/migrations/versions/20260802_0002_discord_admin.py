"""Add Discord identity and versioned administration state.

Historical revision kept as an explicit snapshot: it never imports current
ORM models so future model changes cannot leak into a fresh migration chain.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

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

    op.create_table(
        "discord_account_links",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("discord_user_id", sa.String(), nullable=False, unique=True),
        sa.Column("twitch_user_id", sa.String(), nullable=False, unique=True),
        sa.Column("twitch_login", sa.String(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "discord_guild_bindings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("discord_guild_id", sa.String(), nullable=False, unique=True),
        sa.Column("channel_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("configured_by_discord_id", sa.String(), nullable=False),
        sa.Column("management_channel_id", sa.String(), nullable=True),
        sa.Column("locale", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"]),
    )
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("channel_twitch_id", sa.String(), nullable=False),
        sa.Column("actor_twitch_id", sa.String(), nullable=False),
        sa.Column("actor_discord_id", sa.String(), nullable=True),
        sa.Column("actor_service", sa.String(), nullable=False),
        sa.Column("guild_id", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("before_json", postgresql.JSONB(), nullable=False),
        sa.Column("after_json", postgresql.JSONB(), nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.CheckConstraint("result IN ('success','error')", name="ck_admin_audit_log_result"),
    )
    for index_name, column in (
        ("ix_admin_audit_log_created_at", "created_at"),
        ("ix_admin_audit_log_request_id", "request_id"),
        ("ix_admin_audit_log_idempotency_key", "idempotency_key"),
        ("ix_admin_audit_log_channel_twitch_id", "channel_twitch_id"),
        ("ix_admin_audit_log_actor_twitch_id", "actor_twitch_id"),
        ("ix_admin_audit_log_actor_discord_id", "actor_discord_id"),
        ("ix_admin_audit_log_guild_id", "guild_id"),
        ("ix_admin_audit_log_action", "action"),
    ):
        op.create_index(index_name, "admin_audit_log", [column])
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("actor_scope", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("actor_scope", "idempotency_key", name="uq_idempotency_actor_key"),
    )
    op.create_index("ix_idempotency_records_expires_at", "idempotency_records", ["expires_at"])

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
