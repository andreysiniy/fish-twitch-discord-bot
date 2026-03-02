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

CREATE TEMP TABLE tmp_item_definition_id_map (
    old_id VARCHAR PRIMARY KEY,
    new_id VARCHAR NOT NULL
) ON COMMIT DROP;

INSERT INTO tmp_item_definition_id_map (old_id, new_id)
SELECT
    d.id AS old_id,
    CONCAT(d.channel_twitch_id, '::', d.item_id) AS new_id
FROM item_definitions d
WHERE d.id IS DISTINCT FROM CONCAT(d.channel_twitch_id, '::', d.item_id);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM tmp_item_definition_id_map m
        JOIN item_definitions d ON d.id = m.new_id
    ) THEN
        RAISE EXCEPTION 'Cannot migrate item_definitions.id: target scoped id already exists';
    END IF;
END
$$;

UPDATE item_definitions d
SET id = m.new_id
FROM tmp_item_definition_id_map m
WHERE d.id = m.old_id;

UPDATE inventory_items i
SET item_id = m.new_id
FROM tmp_item_definition_id_map m
WHERE i.item_id = m.old_id;

UPDATE location_items l
SET item_id = m.new_id
FROM tmp_item_definition_id_map m
WHERE l.item_id = m.old_id;

ALTER TABLE inventory_items
    ADD CONSTRAINT inventory_items_item_id_fkey
        FOREIGN KEY (item_id) REFERENCES item_definitions(id);

ALTER TABLE location_items
    ADD CONSTRAINT location_items_item_id_fkey
        FOREIGN KEY (item_id) REFERENCES item_definitions(id);

COMMIT;
