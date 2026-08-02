import os

import pytest
from infrastructure.database import SessionLocal
from infrastructure.models import Channel, ItemDefinition, LocationItem, RewardPool
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
        drop = LocationItem(
            reward_pool_id=pool.id,
            item_id=definition.id,
            weight=25,
            xp_gain=3,
            quantity=7,
            message="You found an item!",
        )
        db.add(drop)
        db.flush()
        original_id = drop.id
        original_version = drop.version

        ChannelRepository(db).update_rewards(
            channel.id,
            "default",
            [{"type": "nothing", "weight": 100, "message": "No catch."}],
            0.25,
            {"level": 2},
            "Updated Lake",
        )

        preserved = db.query(LocationItem).filter(LocationItem.id == original_id).one()
        assert preserved.quantity == 7
        assert preserved.version == original_version
        assert preserved.weight == 25
        assert preserved.message == "You found an item!"
    finally:
        db.rollback()
        db.close()
