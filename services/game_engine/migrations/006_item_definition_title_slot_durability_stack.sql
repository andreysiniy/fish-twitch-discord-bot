BEGIN;

ALTER TABLE item_definitions
    ADD COLUMN IF NOT EXISTS title VARCHAR,
    ADD COLUMN IF NOT EXISTS slot VARCHAR,
    ADD COLUMN IF NOT EXISTS durability INTEGER,
    ADD COLUMN IF NOT EXISTS stack_size INTEGER NOT NULL DEFAULT 1;

UPDATE item_definitions
SET title = COALESCE(NULLIF(title, ''), name, id);

UPDATE item_definitions
SET stack_size = COALESCE(stack_size, 1);

ALTER TABLE item_definitions
    ALTER COLUMN title SET NOT NULL,
    ALTER COLUMN stack_size SET NOT NULL,
    ALTER COLUMN stack_size SET DEFAULT 1;

ALTER TABLE item_definitions
    DROP COLUMN IF EXISTS name;

COMMIT;
