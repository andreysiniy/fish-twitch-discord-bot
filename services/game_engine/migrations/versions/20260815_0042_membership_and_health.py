"""Add durable Twitch membership and StreamElements health state."""

import os

import sqlalchemy as sa
from alembic import op


revision = "20260815_0042"
down_revision = "20260814_0041"
branch_labels = None
depends_on = None



def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("twitch_bot_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "channels",
        sa.Column(
            "bot_membership_updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "channels",
        sa.Column("bot_membership_updated_by_discord_id", sa.String(), nullable=True),
    )

    health_columns = (
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_validation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_latency_ms", sa.Integer(), nullable=True),
    )
    for column in health_columns:
        op.add_column("channel_integrations", column)

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE channel_integrations SET status = 'degraded' WHERE status = 'error'"
        )
    )
    op.drop_constraint("ck_channel_integrations_status", "channel_integrations", type_="check")
    op.create_check_constraint(
        "ck_channel_integrations_status",
        "channel_integrations",
        "status IN ('connected','degraded','invalid','disconnected')",
    )
    op.create_check_constraint(
        "ck_channel_integrations_failures_nonnegative",
        "channel_integrations",
        "consecutive_failures >= 0",
    )
    op.create_check_constraint(
        "ck_channel_integrations_latency_nonnegative",
        "channel_integrations",
        "validation_latency_ms IS NULL OR validation_latency_ms >= 0",
    )

    bind.execute(
        sa.text(
            "UPDATE channel_integrations SET next_validation_at = now() "
            "WHERE status = 'connected'"
        )
    )

    # Transitional bootstrap: only existing channels are enabled.  Unknown
    # logins are deliberately not created without a verified Twitch identity.
    raw = os.getenv("BOOTSTRAP_CHANNELS") or os.getenv("INITIAL_CHANNELS") or ""
    for login in (value.strip().lower() for value in raw.split(",")):
        if not login:
            continue
        bind.execute(
            sa.text(
                "UPDATE channels SET twitch_bot_enabled = true "
                "WHERE lower(name) = :login OR lower(twitch_id) = :login"
            ),
            {"login": login},
        )


def downgrade() -> None:
    op.drop_constraint(
        "ck_channel_integrations_latency_nonnegative", "channel_integrations", type_="check"
    )
    op.drop_constraint(
        "ck_channel_integrations_failures_nonnegative", "channel_integrations", type_="check"
    )
    op.drop_constraint("ck_channel_integrations_status", "channel_integrations", type_="check")
    op.create_check_constraint(
        "ck_channel_integrations_status",
        "channel_integrations",
        "status IN ('connected','disconnected','invalid','error')",
    )
    for column in (
        "validation_latency_ms",
        "consecutive_failures",
        "next_validation_at",
        "last_error_at",
        "last_success_at",
        "last_check_at",
    ):
        op.drop_column("channel_integrations", column)
    for column in (
        "bot_membership_updated_by_discord_id",
        "bot_membership_updated_at",
        "twitch_bot_enabled",
    ):
        op.drop_column("channels", column)
