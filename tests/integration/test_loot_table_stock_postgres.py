import os
import uuid

import pytest
from infrastructure.database import SessionLocal
from infrastructure.models import (
    Channel,
    FishingCastItemDrop,
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


@pytest.mark.integration
def test_loot_table_drop_records_definition_id_not_entry_id() -> None:
    """Ledger stores the item definition id, not the loot-table entry id.

    Regression: the drop candidate carries db_id = loot_table_entries.id while
    fishing_cast_item_drops.item_definition_id must reference item_definitions;
    mixing them up broke the composite FK and surfaced as a 500 on chat casts.
    """
    from decimal import Decimal

    from domain.schemas.fishing import FishingResult
    from infrastructure.models import UserProgress
    from services.fishing.ledger_service import FishingLedgerService

    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel = Channel(twitch_id=f"drop-fk-{suffix}", name="Drop FK", config={})
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id="drop-viewer",
            username="drop_viewer",
            channel_id=channel.id,
            current_mass=Decimal("10"),
            total_mass_stat=Decimal("10"),
        )
        db.add(user)
        definition = ItemDefinition(
            channel_id=channel.id,
            item_id="drop_rod",
            title="Drop Rod",
            type="equipment",
            slot="rod",
            rarity="common",
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
        )
        db.add(entry)
        db.flush()
        pool = RewardPool(
            channel_id=channel.id,
            location_id="lake",
            items_drop_rate=1.0,
            item_loot_table_id=table.id,
            rewards_data=[],
            requirements={},
        )
        db.add(pool)
        db.flush()

        repo = ConfigRepository(db)
        _, items, _ = repo.get_dual_pool(channel.twitch_id, "lake")
        assert items[0]["item_definition_id"] == definition.id
        assert items[0]["loot_table_entry_id"] == entry.id
        assert items[0]["db_id"] == entry.id

        ledger = FishingLedgerService(db)
        cast = ledger.repo.create_cast(
            channel_id=channel.id,
            user_progress_id=user.id,
            source="twitch",
            source_request_id=f"drop-fk-{suffix}",
            status="resolved",
            twitch_user_id_snapshot="drop-viewer",
            username_snapshot="drop_viewer",
            location_id="lake",
        )
        result = FishingResult(
            loot={"type": "fish", "weight": 100},
            item_drop=items[0],
            username="drop_viewer",
            xp_gained=5,
            mass_gained=Decimal("0"),
            is_level_up=False,
            old_level=1,
            new_level=1,
        )
        ledger._record_item_drop(cast, result)
        db.flush()

        drop = (
            db.query(FishingCastItemDrop)
            .filter(FishingCastItemDrop.cast_id == cast.id)
            .one()
        )
        assert drop.item_definition_id == definition.id
        assert drop.loot_table_entry_id == entry.id
        assert drop.item_id_snapshot == "drop_rod"
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_loot_table_roll_service_reserves_clamped_quantity() -> None:
    """The shared roll service reserves the rolled quantity and clamps it."""
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel = Channel(twitch_id=f"clamp-{suffix}", name="Clamp", config={})
        db.add(channel)
        db.flush()
        definition = ItemDefinition(
            channel_id=channel.id,
            item_id="clamp_rod",
            title="Clamp Rod",
            type="equipment",
            slot="rod",
            rarity="rare",
            stack_size=1,
        )
        db.add(definition)
        db.flush()
        table = LootTable(channel_id=channel.id, table_id="clamp_table", title="Clamp")
        db.add(table)
        db.flush()
        entry = LootTableEntry(
            loot_table_id=table.id,
            channel_id=channel.id,
            item_definition_id=definition.id,
            weight=100,
            xp_gain=5,
            min_quantity=3,
            max_quantity=5,
        )
        db.add(entry)
        db.flush()
        db.add(LootTableEntryStock(loot_table_entry_id=entry.id, remaining_quantity=2))
        db.commit()

        from services.loot_table_service import LootTableRollService

        rolls = iter([0.0, 0.9])
        resolutions = LootTableRollService(db).roll(
            channel.id,
            "clamp_table",
            rolls=1,
            random_source=lambda: next(rolls),
        )
        assert len(resolutions) == 1
        resolution = resolutions[0]
        assert resolution.quantity_requested == 5
        assert resolution.quantity_granted == 2
        assert resolution.stock_before == 2
        assert resolution.stock_after == 0
        assert resolution.status == "selected"
        stock = (
            db.query(LootTableEntryStock)
            .filter(LootTableEntryStock.loot_table_entry_id == entry.id)
            .one()
        )
        assert stock.remaining_quantity == 0
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_loot_table_roll_service_skips_exhausted_entries() -> None:
    """Stock=0 entries never win the roll; the service returns no drop."""
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel = Channel(twitch_id=f"empty-{suffix}", name="Empty", config={})
        db.add(channel)
        db.flush()
        definition = ItemDefinition(
            channel_id=channel.id,
            item_id="empty_rod",
            title="Empty Rod",
            type="equipment",
            slot="rod",
            rarity="common",
            stack_size=1,
        )
        db.add(definition)
        db.flush()
        table = LootTable(channel_id=channel.id, table_id="empty_table", title="Empty")
        db.add(table)
        db.flush()
        entry = LootTableEntry(
            loot_table_id=table.id,
            channel_id=channel.id,
            item_definition_id=definition.id,
            weight=100,
            min_quantity=1,
            max_quantity=1,
        )
        db.add(entry)
        db.flush()
        db.add(LootTableEntryStock(loot_table_entry_id=entry.id, remaining_quantity=0))
        db.commit()

        from services.loot_table_service import LootTableRollService

        resolutions = LootTableRollService(db).roll(
            channel.id, "empty_table", rolls=3, random_source=lambda: 0.0
        )
        assert resolutions == []
        stock = (
            db.query(LootTableEntryStock)
            .filter(LootTableEntryStock.loot_table_entry_id == entry.id)
            .one()
        )
        assert stock.remaining_quantity == 0
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_fishing_and_lootbox_share_candidates_and_selection() -> None:
    """Both drop paths resolve the same candidates and pick the same entry."""
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel = Channel(twitch_id=f"shared-{suffix}", name="Shared", config={})
        db.add(channel)
        db.flush()
        rod = ItemDefinition(
            channel_id=channel.id,
            item_id="shared_rod",
            title="Shared Rod",
            type="equipment",
            slot="rod",
            rarity="rare",
            stack_size=1,
        )
        bait = ItemDefinition(
            channel_id=channel.id,
            item_id="shared_bait",
            title="Shared Bait",
            type="material",
            rarity="common",
            stack_size=10,
        )
        db.add_all([rod, bait])
        db.flush()
        table = LootTable(channel_id=channel.id, table_id="shared_table", title="Shared")
        db.add(table)
        db.flush()
        rod_entry = LootTableEntry(
            loot_table_id=table.id,
            channel_id=channel.id,
            item_definition_id=rod.id,
            weight=70,
            min_quantity=1,
            max_quantity=1,
        )
        bait_entry = LootTableEntry(
            loot_table_id=table.id,
            channel_id=channel.id,
            item_definition_id=bait.id,
            weight=30,
            min_quantity=2,
            max_quantity=4,
        )
        db.add_all([rod_entry, bait_entry])
        db.flush()
        db.add_all(
            [
                LootTableEntryStock(loot_table_entry_id=rod_entry.id, remaining_quantity=5),
                LootTableEntryStock(loot_table_entry_id=bait_entry.id, remaining_quantity=3),
            ]
        )
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

        from domain.logic.loot_selection import select_item_drop
        from services.loot_table_service import LootTableRollService

        _, fishing_items, _ = ConfigRepository(db).get_dual_pool(channel.twitch_id, "lake")
        lootbox_items = LootTableRollService(db).resolve_candidates(channel.id, "shared_table")

        def comparable(candidates: list[dict]) -> list[dict]:
            return sorted(
                (
                    {
                        "item_id": candidate["item_id"],
                        "weight": candidate["weight"],
                        "remaining_stock": candidate["remaining_stock"],
                        "min_quantity": candidate["min_quantity"],
                        "max_quantity": candidate["max_quantity"],
                    }
                    for candidate in candidates
                ),
                key=lambda candidate: candidate["item_id"],
            )

        assert comparable(fishing_items) == comparable(lootbox_items)

        fishing_hit = select_item_drop(fishing_items, random_source=lambda: 0.1)
        lootbox_hit = select_item_drop(lootbox_items, random_source=lambda: 0.1)
        assert fishing_hit is not None and lootbox_hit is not None
        assert fishing_hit.item_id == lootbox_hit.item_id
        assert fishing_hit.quantity_rolled == lootbox_hit.quantity_rolled
    finally:
        db.rollback()
        db.close()

