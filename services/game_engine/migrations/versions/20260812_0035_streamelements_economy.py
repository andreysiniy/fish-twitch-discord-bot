"""Add provider integrations, economy settings and forensic operation ledger."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260812_0035"
down_revision = "20260811_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(), nullable=False, server_default="streamelements"),
        sa.Column("provider_channel_id", sa.String(), nullable=False),
        sa.Column("credential_ciphertext", sa.Text(), nullable=False),
        sa.Column("credential_key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("credential_fingerprint", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="connected"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_validated_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("channel_id", "provider", name="uq_channel_integrations_channel_provider"),
        sa.CheckConstraint("provider = 'streamelements'", name="ck_channel_integrations_provider"),
        sa.CheckConstraint(
            "status IN ('connected','disconnected','invalid','error')",
            name="ck_channel_integrations_status",
        ),
        sa.CheckConstraint("credential_key_version >= 1", name="ck_channel_integrations_key_version"),
    )
    op.create_index("ix_channel_integrations_channel_id", "channel_integrations", ["channel_id"])

    op.create_table(
        "channel_economy_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pricing_mode", sa.String(), nullable=False, server_default="single_rate"),
        sa.Column("buy_points_per_kg", sa.Numeric(18, 4), nullable=False, server_default="120"),
        sa.Column("sell_points_per_kg", sa.Numeric(18, 4), nullable=False, server_default="100"),
        sa.Column("buy_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sell_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("min_transaction_mass", sa.Numeric(18, 2), nullable=False, server_default="0.01"),
        sa.Column("max_transaction_mass", sa.Numeric(18, 2), nullable=False, server_default="1000"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("channel_id", name="uq_channel_economy_settings_channel"),
        sa.CheckConstraint("pricing_mode IN ('single_rate','spread')", name="ck_economy_settings_pricing_mode"),
        sa.CheckConstraint("buy_points_per_kg > 0", name="ck_economy_settings_buy_rate_positive"),
        sa.CheckConstraint("sell_points_per_kg > 0", name="ck_economy_settings_sell_rate_positive"),
        sa.CheckConstraint("min_transaction_mass > 0", name="ck_economy_settings_min_mass_positive"),
        sa.CheckConstraint("max_transaction_mass >= min_transaction_mass", name="ck_economy_settings_mass_range"),
    )

    operation_cols = [
        sa.Column("provider", sa.String(), nullable=False, server_default="streamelements"),
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("channel_integrations.id")),
        sa.Column("source", sa.String(), nullable=False, server_default="twitch"),
        sa.Column("source_request_id", sa.String()),
        sa.Column("provider_channel_id_snapshot", sa.String()),
        sa.Column("raw_command_argument", sa.String()),
        sa.Column("argument_mode", sa.String()),
        sa.Column("argument_unit", sa.String()),
        sa.Column("argument_multiplier_kg", sa.Numeric(24, 8)),
        sa.Column("mass_effective", sa.Numeric(18, 2)),
        sa.Column("pricing_mode_snapshot", sa.String()),
        sa.Column("buy_rate_snapshot", sa.Numeric(18, 4)),
        sa.Column("sell_rate_snapshot", sa.Numeric(18, 4)),
        sa.Column("rate_used_snapshot", sa.Numeric(18, 4)),
        sa.Column("settings_version_snapshot", sa.Integer()),
        sa.Column("player_mass_before", sa.Numeric(18, 2)),
        sa.Column("player_mass_after", sa.Numeric(18, 2)),
        sa.Column("provider_balance_before", sa.Integer()),
        sa.Column("provider_balance_after", sa.Integer()),
        sa.Column("provider_status_code", sa.Integer()),
        sa.Column("provider_request_meta", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String()),
        sa.Column("compensation_state", sa.String()),
        sa.Column("reconciliation_reason", sa.Text()),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("external_applied_at", sa.DateTime(timezone=True)),
        sa.Column("internal_applied_at", sa.DateTime(timezone=True)),
    ]
    for column in operation_cols:
        op.add_column("economy_operations", column)
    # Every operation id is generated as a UUID by the application. Fail
    # loudly rather than silently dropping a legacy non-UUID ledger row.
    op.execute(
        sa.text(
            """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM economy_operations WHERE id !~* '^[0-9a-f-]{36}$')
            THEN RAISE EXCEPTION 'economy_operations contains non-UUID ids'; END IF;
            END $$;"""
        )
    )
    op.alter_column(
        "economy_operations",
        "id",
        type_=postgresql.UUID(as_uuid=True),
        postgresql_using="id::uuid",
    )
    op.create_index("ix_economy_operations_integration_id", "economy_operations", ["integration_id"])
    op.create_index("ix_economy_operations_source_request_id", "economy_operations", ["source_request_id"])

    op.create_table(
        "economy_operation_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("economy_operations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("from_state", sa.String()),
        sa.Column("to_state", sa.String()),
        sa.Column("actor_type", sa.String(), nullable=False, server_default="system"),
        sa.Column("actor_id", sa.String()),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("operation_id", "sequence_no", name="uq_economy_operation_events_sequence"),
    )
    op.create_index("ix_economy_operation_events_operation_sequence", "economy_operation_events", ["operation_id", "sequence_no"])
    op.create_index("ix_economy_operation_events_created_at", "economy_operation_events", ["created_at"])

    op.create_table(
        "economy_provider_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("economy_operations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("request_kind", sa.String(), nullable=False),
        sa.Column("points_delta", sa.Integer()),
        sa.Column("request_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_finished_at", sa.DateTime(timezone=True)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("provider_request_id", sa.String()),
        sa.Column("safe_request_meta", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("safe_response_meta", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String()),
        sa.Column("error_message", sa.Text()),
        sa.UniqueConstraint("operation_id", "attempt_no", name="uq_economy_provider_attempts_number"),
    )
    op.create_index("ix_economy_provider_attempts_operation", "economy_provider_attempts", ["operation_id"])

    # Preserve existing encrypted legacy credentials as legacy-key rows. They
    # are rotated to the dedicated key on the next successful connect/update.
    op.execute(
        sa.text(
            """INSERT INTO channel_integrations
              (id, channel_id, provider, provider_channel_id,
               credential_ciphertext, credential_key_version,
               credential_fingerprint, status)
              SELECT gen_random_uuid(), id, 'streamelements', se_channel_id,
                     se_token, 1, 'legacy', 'connected'
                FROM channels
               WHERE se_token IS NOT NULL AND se_channel_id IS NOT NULL
              ON CONFLICT (channel_id, provider) DO NOTHING"""
        )
    )
    # Initialize the new settings from the old custom parameters without
    # deleting the legacy configuration yet.
    op.execute(
        sa.text(
            """INSERT INTO channel_economy_settings
              (id, channel_id, pricing_mode, buy_points_per_kg, sell_points_per_kg)
              SELECT gen_random_uuid(), id, 'single_rate',
                     COALESCE(NULLIF(config->'custom_params'->>'buy_rate','')::numeric, 120),
                     COALESCE(NULLIF(config->'custom_params'->>'sell_rate','')::numeric, 100)
                FROM channels
              ON CONFLICT (channel_id) DO NOTHING"""
        )
    )


def downgrade() -> None:
    op.drop_index("ix_economy_provider_attempts_operation", table_name="economy_provider_attempts")
    op.drop_table("economy_provider_attempts")
    op.drop_index("ix_economy_operation_events_created_at", table_name="economy_operation_events")
    op.drop_index("ix_economy_operation_events_operation_sequence", table_name="economy_operation_events")
    op.drop_table("economy_operation_events")
    op.drop_index("ix_economy_operations_source_request_id", table_name="economy_operations")
    op.drop_index("ix_economy_operations_integration_id", table_name="economy_operations")
    op.alter_column("economy_operations", "id", type_=sa.String(), postgresql_using="id::text")
    for column in (
        "internal_applied_at", "external_applied_at", "started_at", "requested_at",
        "reconciliation_reason", "compensation_state", "error_code", "provider_request_meta",
        "provider_status_code", "provider_balance_after", "provider_balance_before",
        "player_mass_after", "player_mass_before", "settings_version_snapshot", "rate_used_snapshot",
        "sell_rate_snapshot", "buy_rate_snapshot", "pricing_mode_snapshot", "mass_effective",
        "argument_multiplier_kg", "argument_unit", "argument_mode", "raw_command_argument",
        "provider_channel_id_snapshot", "source_request_id", "source", "integration_id", "provider",
    ):
        op.drop_column("economy_operations", column)
    op.drop_table("channel_economy_settings")
    op.drop_index("ix_channel_integrations_channel_id", table_name="channel_integrations")
    op.drop_table("channel_integrations")

