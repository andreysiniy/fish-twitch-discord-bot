BEGIN;

ALTER TABLE fishing_events
    ADD COLUMN IF NOT EXISTS event_title VARCHAR NOT NULL DEFAULT 'Untitled Event';

COMMIT;
