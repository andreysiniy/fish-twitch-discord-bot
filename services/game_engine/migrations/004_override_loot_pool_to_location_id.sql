BEGIN;

ALTER TABLE fishing_events
    ADD COLUMN IF NOT EXISTS override_loot_pool_location_id VARCHAR;

UPDATE fishing_events fe
SET override_loot_pool_location_id = rp.location_id
FROM reward_pools rp
WHERE fe.override_loot_pool IS NOT NULL
  AND rp.id = fe.override_loot_pool;

ALTER TABLE fishing_events
    DROP COLUMN IF EXISTS override_loot_pool;

ALTER TABLE fishing_events
    RENAME COLUMN override_loot_pool_location_id TO override_loot_pool;

COMMIT;
