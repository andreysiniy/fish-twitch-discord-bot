"""Archive and remove legacy economy/robbery channel parameters."""

import sqlalchemy as sa
from alembic import op


revision = "20260814_0041"
down_revision = "20260814_0040"
branch_labels = None
depends_on = None

_LEGACY_KEYS = [
    "sell_max_bonus",
    "sell_mid_level",
    "sell_rate",
    "buy_rate",
    "rob_resist_divisor",
    "rob_loss_divisor",
]


def upgrade() -> None:
    bind = op.get_bind()
    # Ensure channels created after the original economy migration still have
    # normalized settings before the legacy JSON keys are removed.
    bind.execute(
        sa.text(
            """INSERT INTO channel_economy_settings
              (id, channel_id, buy_points_per_kg, sell_points_per_kg)
              SELECT gen_random_uuid(), c.id,
                     COALESCE(NULLIF(c.config->'custom_params'->>'buy_rate','')::numeric, 120),
                     COALESCE(NULLIF(c.config->'custom_params'->>'sell_rate','')::numeric, 100)
                FROM channels c
               WHERE NOT EXISTS (
                     SELECT 1 FROM channel_economy_settings s
                      WHERE s.channel_id = c.id
               )
                 AND c.config ? 'custom_params'"""
        )
    )

    keys = "{" + ",".join(_LEGACY_KEYS) + "}"
    bind.execute(
        sa.text(
            """WITH legacy AS (
                SELECT id, twitch_id, config,
                       config->'custom_params' AS custom_params,
                       (config->'custom_params') - CAST(:keys AS text[]) AS cleaned
                  FROM channels
                 WHERE config ? 'custom_params'
                   AND (config->'custom_params') ?| CAST(:keys AS text[])
            )
            INSERT INTO admin_audit_log
              (id, created_at, request_id, idempotency_key,
               channel_twitch_id, actor_twitch_id, actor_service,
               action, entity_type, entity_id, before_json, after_json, result)
            SELECT gen_random_uuid(), now(), :request_id, :request_id,
                   twitch_id, 'migration', 'alembic',
                   'migration.archive_legacy_channel_params', 'channel_config',
                   id::text,
                   jsonb_build_object('custom_params', custom_params),
                   jsonb_build_object('custom_params', cleaned),
                   'success'
              FROM legacy"""
        ),
        {"keys": keys, "request_id": "migration-20260814-0041"},
    )
    bind.execute(
        sa.text(
            """UPDATE channels
                  SET config = jsonb_set(
                      config,
                      '{custom_params}',
                      (config->'custom_params') - CAST(:keys AS text[]),
                      true
                  )
                WHERE config ? 'custom_params'
                  AND (config->'custom_params') ?| CAST(:keys AS text[])"""
        ),
        {"keys": keys},
    )


def downgrade() -> None:
    # Legacy values are intentionally not restored: their exact original
    # payload remains available in admin_audit_log for an explicit review.
    pass
