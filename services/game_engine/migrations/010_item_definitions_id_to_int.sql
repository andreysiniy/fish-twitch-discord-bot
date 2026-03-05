BEGIN;

DO $$
DECLARE
    constraint_record RECORD;
BEGIN
    FOR constraint_record IN
        SELECT c.conname, c.conrelid::regclass AS table_name
        FROM pg_constraint c
        WHERE c.contype = 'f'
          AND c.confrelid = 'item_definitions'::regclass
          AND c.conrelid IN ('inventory_items'::regclass, 'location_items'::regclass)
    LOOP
        EXECUTE format(
            'ALTER TABLE %s DROP CONSTRAINT %I',
            constraint_record.table_name,
            constraint_record.conname
        );
    END LOOP;
END
$$;

ALTER TABLE item_definitions
    ADD COLUMN id_int SERIAL;

ALTER TABLE inventory_items
    ADD COLUMN item_id_int INTEGER;

ALTER TABLE location_items
    ADD COLUMN item_id_int INTEGER;

UPDATE inventory_items i
SET item_id_int = d.id_int
FROM item_definitions d
WHERE i.item_id = d.id;

UPDATE location_items l
SET item_id_int = d.id_int
FROM item_definitions d
WHERE l.item_id = d.id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM inventory_items
        WHERE item_id_int IS NULL
    ) THEN
        RAISE EXCEPTION 'Cannot migrate inventory_items.item_id to int: unresolved references';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM location_items
        WHERE item_id_int IS NULL
    ) THEN
        RAISE EXCEPTION 'Cannot migrate location_items.item_id to int: unresolved references';
    END IF;
END
$$;

ALTER TABLE item_definitions
    DROP CONSTRAINT IF EXISTS item_definitions_pkey;

ALTER TABLE item_definitions
    DROP COLUMN id;

ALTER TABLE item_definitions
    RENAME COLUMN id_int TO id;

ALTER TABLE item_definitions
    ADD CONSTRAINT item_definitions_pkey PRIMARY KEY (id);

ALTER TABLE inventory_items
    DROP COLUMN item_id;

ALTER TABLE inventory_items
    RENAME COLUMN item_id_int TO item_id;

ALTER TABLE inventory_items
    ALTER COLUMN item_id SET NOT NULL;

ALTER TABLE location_items
    DROP COLUMN item_id;

ALTER TABLE location_items
    RENAME COLUMN item_id_int TO item_id;

ALTER TABLE location_items
    ALTER COLUMN item_id SET NOT NULL;

ALTER TABLE inventory_items
    ADD CONSTRAINT inventory_items_item_id_fkey
        FOREIGN KEY (item_id) REFERENCES item_definitions(id);

ALTER TABLE location_items
    ADD CONSTRAINT location_items_item_id_fkey
        FOREIGN KEY (item_id) REFERENCES item_definitions(id);

CREATE INDEX IF NOT EXISTS ix_item_definitions_id ON item_definitions (id);
CREATE INDEX IF NOT EXISTS ix_inventory_items_item_id ON inventory_items (item_id);
CREATE INDEX IF NOT EXISTS ix_location_items_item_id ON location_items (item_id);

COMMIT;
