"""Create an explicit baseline for the pre-Discord managed schema."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260802_0001"
down_revision = None
branch_labels = None
depends_on = None


JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("twitch_id", sa.String(), nullable=False),
        sa.Column("name", sa.String()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("se_token", sa.String()),
        sa.Column("se_channel_id", sa.String()),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("twitch_id", name="uq_channels_twitch_id"),
    )
    op.create_index("ix_channels_twitch_id", "channels", ["twitch_id"])

    op.create_table(
        "channel_access_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("user_twitch_id", sa.String(), nullable=False),
        sa.Column("user_twitch_name", sa.String(), nullable=False, server_default=""),
        sa.Column("role", sa.String(), nullable=False, server_default="editor"),
        sa.UniqueConstraint("channel_id", "user_twitch_id", name="uq_channel_user_access"),
    )
    op.create_index("ix_channel_access_roles_channel_id", "channel_access_roles", ["channel_id"])
    op.create_index(
        "ix_channel_access_roles_user_twitch_id", "channel_access_roles", ["user_twitch_id"]
    )

    op.create_table(
        "users_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_twitch_id", sa.String(), nullable=False),
        sa.Column("username", sa.String()),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_fish_stat", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_mass_stat", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("current_mass", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("current_location_id", sa.String(), nullable=False, server_default="default"),
        sa.Column(
            "inventory",
            JSONB,
            nullable=False,
            server_default=sa.text(
                "jsonb_build_object('equipped_rod_slot', NULL, 'max_slots', 20)"
            ),
        ),
        sa.UniqueConstraint(
            "channel_id", "user_twitch_id", name="uq_user_progress_channel_user"
        ),
    )
    op.create_index("ix_users_progress_user_twitch_id", "users_progress", ["user_twitch_id"])
    op.create_index("ix_users_progress_channel_id", "users_progress", ["channel_id"])

    op.create_table(
        "item_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String()),
        sa.Column("type", sa.String(), nullable=False, server_default="equipment"),
        sa.Column("slot", sa.String()),
        sa.Column("rarity", sa.String(), nullable=False, server_default="common"),
        sa.Column("durability", sa.Integer()),
        sa.Column("stack_size", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("image_url", sa.String()),
        sa.Column("base_stats", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_sellable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_tradeable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint(
            "channel_id", "item_id", name="uq_item_definitions_channel_item"
        ),
    )
    op.create_index("ix_item_definitions_channel_id", "item_definitions", ["channel_id"])
    op.create_index("ix_item_definitions_item_id", "item_definitions", ["item_id"])

    op.create_table(
        "inventory_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users_progress.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("item_definitions.id"), nullable=False),
        sa.Column("slot_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_durability", sa.Integer()),
        sa.Column("meta", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("user_id", "slot_id", name="uq_inventory_item_user_slot"),
    )
    op.create_index("ix_inventory_items_user_id", "inventory_items", ["user_id"])
    op.create_index("ix_inventory_items_item_id", "inventory_items", ["item_id"])

    op.create_table(
        "reward_pools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("location_id", sa.String(), nullable=False),
        sa.Column("location_name", sa.String()),
        sa.Column("rewards_data", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("requirements", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("items_drop_rate", sa.Float(), nullable=False, server_default="0.1"),
        sa.UniqueConstraint(
            "channel_id", "location_id", name="uq_reward_pool_channel_location"
        ),
    )
    op.create_index("ix_reward_pools_location_id", "reward_pools", ["location_id"])

    op.create_table(
        "location_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reward_pool_id", sa.Integer(), sa.ForeignKey("reward_pools.id"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("item_definitions.id"), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("xp_gain", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity", sa.Integer()),
        sa.Column("message", sa.String(), nullable=False, server_default="You caught {name}!"),
    )
    op.create_index("ix_location_items_item_id", "location_items", ["item_id"])

    op.create_table(
        "fishing_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("event_title", sa.String(), nullable=False, server_default="Untitled Event"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("modifiers", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("override_loot_pool", sa.String()),
    )
    op.create_index(
        "uq_fishing_events_active_per_channel",
        "fishing_events",
        ["channel_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index("ix_fishing_events_channel_id", "fishing_events", ["channel_id"])

    op.create_table(
        "economy_operations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("operation_type", sa.String(), nullable=False),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users_progress.id"), nullable=False),
        sa.Column("twitch_username", sa.String(), nullable=False),
        sa.Column("mass_delta", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("points_delta", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(), nullable=False, server_default="pending"),
        sa.Column("external_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("response_payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_economy_operations_idempotency_key"),
    )
    op.create_index("ix_economy_operations_state", "economy_operations", ["state"])
    op.create_index("ix_economy_operations_channel_id", "economy_operations", ["channel_id"])
    op.create_index("ix_economy_operations_user_id", "economy_operations", ["user_id"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("state", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_events_idempotency_key"),
    )
    op.create_index("ix_outbox_events_state", "outbox_events", ["state"])
    op.create_index("ix_outbox_events_topic", "outbox_events", ["topic"])
    op.create_index("ix_outbox_events_next_attempt_at", "outbox_events", ["next_attempt_at"])


def downgrade() -> None:
    for table_name in (
        "outbox_events",
        "economy_operations",
        "fishing_events",
        "location_items",
        "reward_pools",
        "inventory_items",
        "item_definitions",
        "users_progress",
        "channel_access_roles",
        "channels",
    ):
        op.drop_table(table_name)
