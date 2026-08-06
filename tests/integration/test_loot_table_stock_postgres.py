import os
import uuid

import pytest
from infrastructure.database import SessionLocal
from infrastructure.models import (
    Channel,
    ItemDefinition,
    LootTable,
    LootTableEntry,
    LootTableEntryStock,
    RewardPool,
)
from infrastructure.repositories.config_repo import ConfigRepository


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="requires PostgreSQL",
)


@pytest.mark.integration
def test_loot_table_sources_item_entries_and_consumes_stock() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel = Channel(twitch_id=f"loot-{suffix}", name="Loot", config={})
        db.add(channel)
        db.flush()
        definition = ItemDefinition(
            channel_id=channel.id,
            item_id="loot_rod",
            title="Loot Rod",
            type="equipment",
            slot="rod",
            rarity="rare",
            stack_size=1,
        )
        db.add(definition)
        db.flush()
        table = LootTable(channel_id=channel.id, table_id="lake_items", title="Lake Items")
        db.add(table)
        db.flush()
        entry = LootTableEntry(
            loot_table_id=table.id,
            channel_id=channel.id,
            item_definition_id=definition.id,
            weight=100,
            xp_gain=5,
            message="You found a rod",
        )
        db.add(entry)
        db.flush()
        db.add(LootTableEntryStock(loot_table_entry_id=entry.id, remaining_quantity=2))
        pool = RewardPool(
            channel_id=channel.id,
            location_id="lake",
            items_drop_rate=0.5,
            item_loot_table_id=table.id,
            rewards_data=[],
            requirements={},
        )
        db.add(pool)
        db.commit()

        repo = ConfigRepository(db)
        rewards, items, rate = repo.get_dual_pool(channel.twitch_id, "lake")
        assert len(items) == 1
        assert items[0]["_source"] == "loot_table"
        assert items[0]["item_id"] == "loot_rod"
        assert items[0]["xp_gain"] == 5

        # Stock consumption is atomic across grants.
        assert repo.consume_item_stock(items[0], amount=1) is True
        assert repo.consume_item_stock(items[0], amount=1) is True
        assert repo.consume_item_stock(items[0], amount=1) is False
    finally:
        db.rollback()
        db.close()
