import os

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
from infrastructure.repositories.channel_repo import ChannelRepository


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="requires PostgreSQL",
)


@pytest.mark.integration
def test_reward_update_preserves_item_drop_identity_and_stock() -> None:
    db = SessionLocal()
    try:
        channel = Channel(twitch_id="drop-preservation", name="drop_preservation", config={})
        db.add(channel)
        db.flush()
        pool = RewardPool(
            channel_id=channel.id,
            location_id="default",
            location_name="Default",
            rewards_data=[],
            requirements={},
        )
        definition = ItemDefinition(
            channel_id=channel.id,
            item_id="preserved_item",
            title="Preserved Item",
            type="material",
            rarity="common",
            stack_size=10,
        )
        db.add_all([pool, definition])
        db.flush()
        table = LootTable(
            channel_id=channel.id,
            table_id="preserved-table",
            title="Preserved Table",
            version=1,
            is_active=True,
        )
        db.add(table)
        db.flush()
        entry = LootTableEntry(
            channel_id=channel.id,
            loot_table_id=table.id,
            item_definition_id=definition.id,
            weight=25,
            min_quantity=1,
            max_quantity=1,
            xp_gain=3,
            message="You found an item!",
        )
        db.add(entry)
        db.flush()
        stock = LootTableEntryStock(
            loot_table_entry_id=entry.id, remaining_quantity=7, version=1
        )
        db.add(stock)
        pool.item_loot_table_id = table.id
        db.flush()
        original_id = entry.id
        original_version = entry.version

        ChannelRepository(db).update_rewards(
            channel.id,
            "default",
            [{"type": "nothing", "weight": 100, "message": "No catch."}],
            0.25,
            {"level": 2},
            "Updated Lake",
        )

        preserved = db.query(LootTableEntry).filter(LootTableEntry.id == original_id).one()
        preserved_stock = (
            db.query(LootTableEntryStock)
            .filter(LootTableEntryStock.loot_table_entry_id == original_id)
            .one()
        )
        assert preserved_stock.remaining_quantity == 7
        assert preserved.version == original_version
        assert preserved.weight == 25
        assert preserved.message == "You found an item!"
    finally:
        db.rollback()
        db.close()
