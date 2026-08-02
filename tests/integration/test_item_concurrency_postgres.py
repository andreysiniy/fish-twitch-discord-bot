import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from infrastructure.database import SessionLocal
from infrastructure.models import (
    Channel,
    InventoryItem,
    ItemDefinition,
    LocationItem,
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
            inventory={"max_slots": 1, "equipped_rod_slot": None},
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
                inventory={"max_slots": 1, "equipped_rod_slot": None},
            )
            for index in range(2)
        ]
        setup.add_all([pool, definition, *users])
        setup.flush()
        drop = LocationItem(
            reward_pool_id=pool.id,
            item_id=definition.id,
            weight=1,
            quantity=1,
            message="Last item dropped.",
        )
        setup.add(drop)
        setup.commit()
        drop_id = drop.id
        user_ids = [user.id for user in users]
    finally:
        setup.close()

    barrier = threading.Barrier(2)

    def consume_and_grant(user_id: int) -> bool:
        db = SessionLocal()
        try:
            user = db.get(UserProgress, user_id)
            barrier.wait(timeout=10)
            consumed = ConfigRepository(db).consume_location_item_stock(drop_id)
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
        drop = verify.get(LocationItem, drop_id)
        inventory_count = (
            verify.query(InventoryItem)
            .filter(InventoryItem.user_id.in_(user_ids))
            .count()
        )
        assert sorted(results) == [False, True]
        assert drop.quantity == 0
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
