import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from infrastructure.database import SessionLocal
from infrastructure.models import (
    EquippedItem,
    Channel,
    InventoryItem,
    ItemDefinition,
    LootTable,
    LootTableEntry,
    LootTableEntryStock,
    RewardPool,
    UserProgress,
)
from infrastructure.repositories.config_repo import ConfigRepository
from infrastructure.repositories.inventory_repo import InventoryRepository
from infrastructure.repositories.user_repo import UserRepository

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="requires PostgreSQL",
)


@pytest.mark.integration
def test_concurrent_grants_fill_one_stack_without_lost_updates() -> None:
    suffix = uuid.uuid4().hex
    setup = SessionLocal()
    try:
        channel = Channel(twitch_id=f"grant-race-{suffix}", name="Grant race", config={})
        setup.add(channel)
        setup.flush()
        user = UserProgress(
            user_twitch_id=f"grant-user-{suffix}",
            username="grant_user",
            channel_id=channel.id,
            base_inventory_slots=1,
        )
        definition = ItemDefinition(
            channel_id=channel.id,
            item_id="race_material",
            title="Race Material",
            type="material",
            stack_size=10,
            effects=[],
        )
        setup.add_all([user, definition])
        setup.commit()
        user_id = user.id
    finally:
        setup.close()

    barrier = threading.Barrier(2)

    def grant() -> None:
        db = SessionLocal()
        try:
            locked_user = db.get(UserProgress, user_id)
            barrier.wait(timeout=10)
            InventoryRepository(db).grant_many(
                locked_user, [{"item_id": "race_material", "quantity": 5}]
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(grant) for _ in range(2)]
        for future in futures:
            future.result(timeout=15)

    verify = SessionLocal()
    try:
        rows = verify.query(InventoryItem).filter(InventoryItem.user_id == user_id).all()
        assert [(row.slot_id, row.quantity) for row in rows] == [(1, 10)]
    finally:
        verify.close()


@pytest.mark.integration
def test_finite_location_stock_is_consumed_by_only_one_concurrent_grant() -> None:
    suffix = uuid.uuid4().hex
    setup = SessionLocal()
    try:
        channel = Channel(twitch_id=f"stock-race-{suffix}", name="Stock race", config={})
        setup.add(channel)
        setup.flush()
        pool = RewardPool(
            channel_id=channel.id,
            location_id="race",
            location_name="Race Lake",
            rewards_data=[],
            requirements={},
        )
        definition = ItemDefinition(
            channel_id=channel.id,
            item_id="last_item",
            title="Last Item",
            type="material",
            stack_size=1,
            effects=[],
        )
        users = [
            UserProgress(
                user_twitch_id=f"stock-user-{index}-{suffix}",
                username=f"stock_user_{index}",
                channel_id=channel.id,
                base_inventory_slots=1,
            )
            for index in range(2)
        ]
        setup.add_all([pool, definition, *users])
        setup.flush()
        table = LootTable(
            channel_id=channel.id,
            table_id=f"stock-race-{suffix}",
            title="Stock Race Table",
            version=1,
            is_active=True,
        )
        setup.add(table)
        setup.flush()
        entry = LootTableEntry(
            channel_id=channel.id,
            loot_table_id=table.id,
            item_definition_id=definition.id,
            weight=1,
            min_quantity=1,
            max_quantity=1,
            message="Last item dropped.",
        )
        setup.add(entry)
        setup.flush()
        stock = LootTableEntryStock(
            loot_table_entry_id=entry.id, remaining_quantity=1, version=1
        )
        setup.add(stock)
        pool.item_loot_table_id = table.id
        setup.commit()
        entry_id = entry.id
        user_ids = [user.id for user in users]
    finally:
        setup.close()

    barrier = threading.Barrier(2)

    def consume_and_grant(user_id: int) -> bool:
        db = SessionLocal()
        try:
            user = db.get(UserProgress, user_id)
            barrier.wait(timeout=10)
            consumed = ConfigRepository(db).consume_loot_table_entry_stock(entry_id)
            if consumed:
                InventoryRepository(db).grant_many(
                    user, [{"item_id": "last_item", "quantity": 1}]
                )
            db.commit()
            return consumed
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(consume_and_grant, user_ids))

    verify = SessionLocal()
    try:
        stock = (
            verify.query(LootTableEntryStock)
            .filter(LootTableEntryStock.loot_table_entry_id == entry_id)
            .one()
        )
        inventory_count = (
            verify.query(InventoryItem)
            .filter(InventoryItem.user_id.in_(user_ids))
            .count()
        )
        assert sorted(results) == [False, True]
        assert stock.remaining_quantity == 0
        assert inventory_count == 1
    finally:
        verify.close()


@pytest.mark.integration
def test_concurrent_robbery_transfers_lock_the_shared_victim() -> None:
    suffix = uuid.uuid4().hex
    setup = SessionLocal()
    try:
        channel = Channel(twitch_id=f"robbery-race-{suffix}", name="Robbery race", config={})
        setup.add(channel)
        setup.flush()
        attackers = [
            UserProgress(
                user_twitch_id=f"attacker-{index}-{suffix}",
                username=f"attacker_{index}",
                channel_id=channel.id,
                current_mass=0,
            )
            for index in range(2)
        ]
        victim = UserProgress(
            user_twitch_id=f"victim-{suffix}",
            username="victim",
            channel_id=channel.id,
            current_mass=100,
        )
        setup.add_all([*attackers, victim])
        setup.commit()
        attacker_ids = [attacker.id for attacker in attackers]
        victim_id = victim.id
    finally:
        setup.close()

    barrier = threading.Barrier(2)

    def transfer(attacker_id: int) -> None:
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            locked = UserRepository(db).lock_users([attacker_id, victim_id])
            locked[attacker_id].current_mass += Decimal("10")
            locked[victim_id].current_mass -= Decimal("10")
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(transfer, attacker_id) for attacker_id in attacker_ids]
        for future in futures:
            future.result(timeout=15)

    verify = SessionLocal()
    try:
        victim = verify.get(UserProgress, victim_id)
        attacker_masses = [
            verify.get(UserProgress, attacker_id).current_mass
            for attacker_id in attacker_ids
        ]
        assert victim.current_mass == Decimal("80.00")
        assert attacker_masses == [Decimal("10.00"), Decimal("10.00")]
    finally:
        verify.close()


@pytest.mark.integration
def test_broken_retain_rod_announces_break_only_once() -> None:
    """A retain_broken rod at zero durability stops emitting break messages."""
    db = SessionLocal()
    try:
        channel = Channel(
            twitch_id=f"break-once-{uuid.uuid4().hex[:8]}",
            name="Break Once",
            config={},
        )
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id="break-user",
            username="break_user",
            channel_id=channel.id,
            current_mass=Decimal("10"),
            total_mass_stat=Decimal("10"),
        )
        db.add(user)
        db.flush()
        definition = ItemDefinition(
            channel_id=channel.id,
            item_id="retain_rod",
            title="Retain Rod",
            type="equipment",
            slot="rod",
            rarity="common",
            stack_size=1,
            max_durability=3,
            break_policy="retain_broken",
        )
        db.add(definition)
        db.flush()
        inv = InventoryItem(
            user_id=user.id,
            channel_id=channel.id,
            item_id=definition.id,
            slot_id=1,
            quantity=1,
            current_durability=1,
        )
        db.add(inv)
        db.flush()
        equipped = EquippedItem(
            user_id=user.id,
            inventory_item_id=inv.id,
            slot="rod",
        )
        db.add(equipped)
        db.flush()

        repo = InventoryRepository(db)
        # First hit breaks the rod: 1 -> 0, break announced once.
        broken = repo.consume_durability(user.id, "rod", 1)
        assert broken == "Retain Rod"

        # Subsequent casts at zero durability must not re-announce.
        again = repo.consume_durability(user.id, "rod", 1)
        assert again is None
        third = repo.consume_durability(user.id, "rod", 1)
        assert third is None
        db.flush()

        # The rod stays equipped (retain_broken) at zero durability.
        db.refresh(inv)
        assert int(inv.current_durability) == 0
    finally:
        db.rollback()
        db.close()
