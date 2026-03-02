BEGIN;

ALTER TABLE item_definitions
    ADD COLUMN IF NOT EXISTS channel_twitch_id VARCHAR,
    ADD COLUMN IF NOT EXISTS item_id VARCHAR;

UPDATE item_definitions
SET item_id = COALESCE(NULLIF(item_id, ''), id)
WHERE item_id IS NULL OR item_id = '';

UPDATE item_definitions
SET channel_twitch_id = COALESCE(NULLIF(channel_twitch_id, ''), 'legacy')
WHERE channel_twitch_id IS NULL OR channel_twitch_id = '';

ALTER TABLE item_definitions
    ALTER COLUMN item_id SET NOT NULL,
    ALTER COLUMN channel_twitch_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_item_definitions_channel_twitch_id
    ON item_definitions (channel_twitch_id);

CREATE INDEX IF NOT EXISTS ix_item_definitions_item_id
    ON item_definitions (item_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_item_definitions_channel_item'
    ) THEN
        ALTER TABLE item_definitions
            ADD CONSTRAINT uq_item_definitions_channel_item
                UNIQUE (channel_twitch_id, item_id);
    END IF;
END
$$;

COMMIT;
