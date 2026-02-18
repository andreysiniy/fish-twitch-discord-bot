BEGIN;

CREATE TABLE IF NOT EXISTS fishing_events (
    id SERIAL PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    modifiers JSONB NOT NULL DEFAULT '{}'::jsonb,
    override_loot_pool INTEGER REFERENCES reward_pools(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_fishing_events_channel_id ON fishing_events (channel_id);
CREATE INDEX IF NOT EXISTS ix_fishing_events_is_active ON fishing_events (is_active);

CREATE UNIQUE INDEX IF NOT EXISTS uq_fishing_events_active_per_channel
ON fishing_events(channel_id)
WHERE is_active = TRUE;

COMMIT;
