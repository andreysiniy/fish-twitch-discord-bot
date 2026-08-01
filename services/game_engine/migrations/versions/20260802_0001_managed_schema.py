"""Adopt managed schema and harden persistence invariants."""

from alembic import op

from infrastructure.database import Base
import infrastructure.models


revision = "20260802_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)

    op.execute(
        """
        ALTER TABLE users_progress
            ALTER COLUMN current_mass TYPE NUMERIC(18, 2)
                USING ROUND(COALESCE(current_mass, 0)::numeric, 2),
            ALTER COLUMN total_mass_stat TYPE NUMERIC(18, 2)
                USING ROUND(COALESCE(total_mass_stat, 0)::numeric, 2),
            ALTER COLUMN current_mass SET DEFAULT 0,
            ALTER COLUMN current_mass SET NOT NULL,
            ALTER COLUMN total_mass_stat SET DEFAULT 0,
            ALTER COLUMN total_mass_stat SET NOT NULL;

        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_user_progress_channel_user') THEN
                ALTER TABLE users_progress ADD CONSTRAINT uq_user_progress_channel_user
                    UNIQUE (channel_id, user_twitch_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_reward_pool_channel_location') THEN
                ALTER TABLE reward_pools ADD CONSTRAINT uq_reward_pool_channel_location
                    UNIQUE (channel_id, location_id);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_inventory_item_user_slot') THEN
                ALTER TABLE inventory_items ADD CONSTRAINT uq_inventory_item_user_slot
                    UNIQUE (user_id, slot_id);
            END IF;
        END
        $$;

        CREATE UNIQUE INDEX IF NOT EXISTS uq_fishing_events_active_per_channel
            ON fishing_events(channel_id) WHERE is_active = TRUE;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_fishing_events_active_per_channel")
    op.execute("ALTER TABLE inventory_items DROP CONSTRAINT IF EXISTS uq_inventory_item_user_slot")
    op.execute("ALTER TABLE reward_pools DROP CONSTRAINT IF EXISTS uq_reward_pool_channel_location")
    op.execute("ALTER TABLE users_progress DROP CONSTRAINT IF EXISTS uq_user_progress_channel_user")
    op.drop_table("outbox_events")
    op.drop_table("economy_operations")
