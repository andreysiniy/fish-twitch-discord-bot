"""Add the fishing cast ledger tables.

Revision ID: 20260802_0007
Revises: 20260802_0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision = "20260802_0007"
down_revision = "20260802_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "fishing_ruleset_snapshots" not in inspector.get_table_names():
        op.create_table(
            "fishing_ruleset_snapshots",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
            ),
            sa.Column("ruleset_hash", sa.String(64), nullable=False),
            sa.Column("channel_config_version", sa.Integer(), nullable=False),
            sa.Column("reward_pool_id", sa.Integer(), nullable=True),
            sa.Column("reward_pool_version", sa.Integer(), nullable=True),
            sa.Column("item_loot_table_id", sa.Integer(), nullable=True),
            sa.Column("item_loot_table_version", sa.Integer(), nullable=True),
            sa.Column("event_id", sa.Integer(), nullable=True),
            sa.Column("event_version", sa.Integer(), nullable=True),
            sa.Column("modifier_schema_version", sa.Integer(), nullable=False),
            sa.Column("engine_version", sa.String(64), nullable=False),
            sa.Column(
                "location_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "reward_entries_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "item_entries_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "effective_params_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "event_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "channel_id", "ruleset_hash", name="uq_ruleset_snapshot_channel_hash"
            ),
        )
        op.create_index(
            "ix_fishing_ruleset_snapshots_channel_id",
            "fishing_ruleset_snapshots",
            ["channel_id"],
        )

    if "fishing_casts" not in inspector.get_table_names():
        op.create_table(
            "fishing_casts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
            ),
            sa.Column(
                "user_progress_id",
                sa.Integer(),
                sa.ForeignKey("users_progress.id"),
                nullable=False,
            ),
            sa.Column(
                "ruleset_snapshot_id",
                sa.String(),
                sa.ForeignKey("fishing_ruleset_snapshots.id"),
                nullable=True,
            ),
            sa.Column("source", sa.String(32), nullable=False, server_default="twitch"),
            sa.Column("source_request_id", sa.String(128), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="resolved"),
            sa.Column("error_code", sa.String(64), nullable=True),
            sa.Column("twitch_user_id_snapshot", sa.String(), nullable=False),
            sa.Column("username_snapshot", sa.String(), nullable=False),
            sa.Column("location_id", sa.String(), nullable=False, server_default="default"),
            sa.Column("location_name_snapshot", sa.String(), nullable=True),
            sa.Column("is_mod", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_sub", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "bypass_cooldown", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("event_id", sa.Integer(), nullable=True),
            sa.Column("event_title_snapshot", sa.String(), nullable=True),
            sa.Column(
                "requested_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "persisted_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column(
                "cooldown_seconds_applied",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("next_available_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("mass_before", sa.Numeric(18, 2), nullable=True),
            sa.Column("mass_after", sa.Numeric(18, 2), nullable=True),
            sa.Column("mass_delta_requested", sa.Numeric(18, 2), nullable=True),
            sa.Column("mass_delta_applied", sa.Numeric(18, 2), nullable=True),
            sa.Column("xp_before", sa.Integer(), nullable=True),
            sa.Column("xp_after", sa.Integer(), nullable=True),
            sa.Column("xp_gained", sa.Integer(), nullable=True),
            sa.Column("level_before", sa.Integer(), nullable=True),
            sa.Column("level_after", sa.Integer(), nullable=True),
            sa.Column("points_delta", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("was_level_up", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("reward_id", sa.String(), nullable=True),
            sa.Column("reward_type", sa.String(), nullable=True),
            sa.Column("reward_weight", sa.Numeric(24, 8), nullable=True),
            sa.Column("reward_total_weight", sa.Numeric(24, 8), nullable=True),
            sa.Column("reward_probability", sa.Numeric(14, 12), nullable=True),
            sa.Column("reward_roll", sa.Numeric(24, 12), nullable=True),
            sa.Column(
                "reward_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("item_drop_probability", sa.Numeric(14, 12), nullable=True),
            sa.Column("item_drop_roll", sa.Numeric(14, 12), nullable=True),
            sa.Column(
                "item_drop_succeeded", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("item_drop_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "resolved_modifiers",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "modifier_sources",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "equipped_items_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "triggered_effects",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "rng_trace",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "special_result",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "result_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "response_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
        op.create_index(
            "ix_fishing_casts_channel_id", "fishing_casts", ["channel_id"]
        )
        op.create_index(
            "ix_fishing_casts_user_progress_id", "fishing_casts", ["user_progress_id"]
        )
        op.create_index(
            "ix_fishing_casts_ruleset_snapshot_id",
            "fishing_casts",
            ["ruleset_snapshot_id"],
        )
        op.create_index(
            "ix_fishing_casts_status", "fishing_casts", ["status"]
        )
        op.create_index(
            "uq_fishing_casts_source_request",
            "fishing_casts",
            ["channel_id", "source", "source_request_id"],
            unique=True,
            postgresql_where=sa.text("source_request_id IS NOT NULL"),
        )
        op.create_index(
            "ix_fishing_casts_channel_requested",
            "fishing_casts",
            ["channel_id", "requested_at", "id"],
        )
        op.create_index(
            "ix_fishing_casts_channel_user",
            "fishing_casts",
            ["channel_id", "user_progress_id", "requested_at"],
        )
        op.create_index(
            "ix_fishing_casts_channel_location",
            "fishing_casts",
            ["channel_id", "location_id", "requested_at"],
        )
        op.create_index(
            "ix_fishing_casts_channel_reward",
            "fishing_casts",
            ["channel_id", "reward_type", "requested_at"],
        )
        op.create_index(
            "ix_fishing_casts_channel_event",
            "fishing_casts",
            ["channel_id", "event_id", "requested_at"],
        )
        op.create_index(
            "ix_fishing_casts_channel_status",
            "fishing_casts",
            ["channel_id", "status", "requested_at"],
        )
        op.create_index(
            "ix_fishing_casts_channel_item_drop",
            "fishing_casts",
            ["channel_id", "requested_at"],
            postgresql_where=sa.text("item_drop_count > 0"),
        )

    if "fishing_cast_item_drops" not in inspector.get_table_names():
        op.create_table(
            "fishing_cast_item_drops",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "cast_id",
                sa.String(),
                sa.ForeignKey("fishing_casts.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False
            ),
            sa.Column("item_definition_id", sa.Integer(), nullable=True),
            sa.Column("item_id_snapshot", sa.String(), nullable=False),
            sa.Column("title_snapshot", sa.String(), nullable=False),
            sa.Column("rarity_snapshot", sa.String(), nullable=True),
            sa.Column("item_type_snapshot", sa.String(), nullable=True),
            sa.Column("definition_version", sa.Integer(), nullable=True),
            sa.Column("loot_table_id", sa.Integer(), nullable=True),
            sa.Column("loot_table_entry_id", sa.Integer(), nullable=True),
            sa.Column("selection_weight", sa.Numeric(24, 8), nullable=True),
            sa.Column("selection_total_weight", sa.Numeric(24, 8), nullable=True),
            sa.Column("selection_probability", sa.Numeric(14, 12), nullable=True),
            sa.Column("selection_roll", sa.Numeric(24, 12), nullable=True),
            sa.Column("quantity_requested", sa.Integer(), nullable=False),
            sa.Column("quantity_granted", sa.Integer(), nullable=False),
            sa.Column(
                "grant_status", sa.String(32), nullable=False, server_default="granted"
            ),
            sa.Column("stock_before", sa.Integer(), nullable=True),
            sa.Column("stock_after", sa.Integer(), nullable=True),
            sa.Column(
                "inventory_grants",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "metadata_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_fishing_cast_item_drops_cast_id",
            "fishing_cast_item_drops",
            ["cast_id"],
        )
        op.create_index(
            "ix_fishing_cast_item_drops_channel_id",
            "fishing_cast_item_drops",
            ["channel_id"],
        )
        op.create_index(
            "ix_cast_item_drops_channel_item",
            "fishing_cast_item_drops",
            ["channel_id", "item_definition_id", "created_at"],
        )
        op.create_index(
            "ix_cast_item_drops_channel_snapshot",
            "fishing_cast_item_drops",
            ["channel_id", "item_id_snapshot", "created_at"],
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "fishing_cast_item_drops" in inspector.get_table_names():
        op.drop_table("fishing_cast_item_drops")
    if "fishing_casts" in inspector.get_table_names():
        op.drop_table("fishing_casts")
    if "fishing_ruleset_snapshots" in inspector.get_table_names():
        op.drop_table("fishing_ruleset_snapshots")
