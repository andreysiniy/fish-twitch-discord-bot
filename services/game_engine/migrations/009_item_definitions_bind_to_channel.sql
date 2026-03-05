BEGIN;

ALTER TABLE item_definitions
    ADD COLUMN IF NOT EXISTS channel_id INTEGER;

INSERT INTO channels (twitch_id, name, is_active, config)
SELECT DISTINCT
    d.channel_twitch_id,
    d.channel_twitch_id,
    TRUE,
    '{"prefix": "!"}'::jsonb
FROM item_definitions d
WHERE d.channel_twitch_id IS NOT NULL
  AND d.channel_twitch_id <> ''
  AND NOT EXISTS (
      SELECT 1
      FROM channels c
      WHERE c.twitch_id = d.channel_twitch_id
  );

UPDATE item_definitions d
SET channel_id = c.id
FROM channels c
WHERE d.channel_id IS NULL
  AND d.channel_twitch_id = c.twitch_id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM item_definitions
        WHERE channel_id IS NULL
    ) THEN
        RAISE EXCEPTION 'Cannot migrate item_definitions: unresolved channel_id';
    END IF;
END
$$;

ALTER TABLE item_definitions
    ALTER COLUMN channel_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'item_definitions_channel_id_fkey'
    ) THEN
        ALTER TABLE item_definitions
            ADD CONSTRAINT item_definitions_channel_id_fkey
                FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS ix_item_definitions_channel_id
    ON item_definitions (channel_id);

ALTER TABLE item_definitions
    DROP CONSTRAINT IF EXISTS uq_item_definitions_channel_item;

ALTER TABLE item_definitions
    ADD CONSTRAINT uq_item_definitions_channel_item UNIQUE (channel_id, item_id);

DROP INDEX IF EXISTS ix_item_definitions_channel_twitch_id;

ALTER TABLE item_definitions
    DROP COLUMN IF EXISTS channel_twitch_id;

COMMIT;
