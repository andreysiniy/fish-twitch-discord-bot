BEGIN;

DROP TABLE IF EXISTS location_items CASCADE;
DROP TABLE IF EXISTS inventory_items CASCADE;
DROP TABLE IF EXISTS item_definitions CASCADE;

CREATE TABLE item_definitions (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    description VARCHAR,
    type VARCHAR NOT NULL DEFAULT 'fish',
    rarity VARCHAR NOT NULL DEFAULT 'common',
    image_url VARCHAR,
    base_stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_sellable BOOLEAN NOT NULL DEFAULT TRUE,
    is_tradeable BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX ix_item_definitions_id ON item_definitions (id);

CREATE TABLE inventory_items (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users_progress(id) ON DELETE CASCADE,
    item_id VARCHAR NOT NULL REFERENCES item_definitions(id),
    slot_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    current_durability INTEGER,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX ix_inventory_items_user_id ON inventory_items (user_id);
CREATE INDEX ix_inventory_items_item_id ON inventory_items (item_id);

CREATE TABLE location_items (
    id SERIAL PRIMARY KEY,
    reward_pool_id INTEGER REFERENCES reward_pools(id) ON DELETE CASCADE,
    item_id VARCHAR NOT NULL REFERENCES item_definitions(id),
    weight INTEGER NOT NULL DEFAULT 100,
    xp_gain INTEGER NOT NULL DEFAULT 0,
    quantity INTEGER,
    message VARCHAR DEFAULT 'You caught {name}!'
);

CREATE INDEX ix_location_items_reward_pool_id ON location_items (reward_pool_id);
CREATE INDEX ix_location_items_item_id ON location_items (item_id);

ALTER TABLE users_progress
    ALTER COLUMN inventory TYPE JSONB USING COALESCE(inventory, '{}'::jsonb);

ALTER TABLE users_progress
    ALTER COLUMN inventory SET DEFAULT '{"equipped_rod_slot": null, "max_slots": 20}'::jsonb;

UPDATE users_progress
SET inventory = jsonb_build_object(
    'equipped_rod_slot', NULL,
    'max_slots', COALESCE((inventory->>'max_slots')::int, 20)
);

COMMIT;
