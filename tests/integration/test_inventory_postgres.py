import os
import uuid
from decimal import Decimal

import pytest

from infrastructure.database import SessionLocal
from infrastructure.models import Channel, InventoryItem, ItemDefinition, UserProgress
from infrastructure.repositories.inventory_repo import (
    InventoryCapacityError,
    InventoryRepository,
)
from infrastructure.repositories.user_repo import UserRepository
from services.inventory_service import InventoryService
from services.player_modifier_service import PlayerModifierService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="requires PostgreSQL",
)


@pytest.mark.integration
def test_grants_stack_reuse_holes_and_rollback_as_one_unit() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex
        channel = Channel(twitch_id=f"inventory-{suffix}", name="Inventory test", config={})
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id=f"user-{suffix}",
            username="inventory_user",
            channel_id=channel.id,
            inventory={"max_slots": 3, "equipped_rod_slot": None},
        )
        stackable = ItemDefinition(
            channel_id=channel.id,
            item_id="test_material",
            title="Test Material",
            type="material",
            stack_size=5,
            effects=[],
        )
        equipment = ItemDefinition(
            channel_id=channel.id,
            item_id="test_rod",
            title="Test Rod",
            type="equipment",
            slot="rod",
            stack_size=1,
            max_durability=10,
            break_policy="destroy_at_zero",
            effects=[],
        )
        db.add_all([user, stackable, equipment])
        db.flush()
        repository = InventoryRepository(db)

        repository.grant_many(user, [{"item_id": "test_material", "quantity": 12}])
        rows = repository._lock_items(user.id)
        assert [(row.slot_id, row.quantity) for row in rows] == [(1, 5), (2, 5), (3, 2)]

        db.delete(rows[1])
        db.flush()
        repository.grant_many(user, [{"item_id": "test_rod", "quantity": 1}])
        rod = (
            db.query(InventoryItem)
            .filter(InventoryItem.user_id == user.id, InventoryItem.item_id == equipment.id)
            .one()
        )
        assert rod.slot_id == 2
        assert rod.current_durability == 10

        before = [(row.slot_id, row.quantity) for row in repository._lock_items(user.id)]
        with pytest.raises(InventoryCapacityError):
            repository.grant_many(
                user,
                [
                    {"item_id": "test_material", "quantity": 1},
                    {"item_id": "test_rod", "quantity": 1},
                ],
            )
        after = [(row.slot_id, row.quantity) for row in repository._lock_items(user.id)]
        assert after == before
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_equipment_durability_obeys_break_policy() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex
        channel = Channel(twitch_id=f"durability-{suffix}", name="Durability test", config={})
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id=f"user-{suffix}",
            username="durability_user",
            channel_id=channel.id,
            inventory={"max_slots": 2, "equipped_rod_slot": None},
        )
        definition = ItemDefinition(
            channel_id=channel.id,
            item_id="fragile_rod",
            title="Fragile Rod",
            type="equipment",
            slot="rod",
            stack_size=1,
            max_durability=1,
            break_policy="destroy_at_zero",
            effects=[],
        )
        db.add_all([user, definition])
        db.flush()
        repository = InventoryRepository(db)
        item = repository.grant_many(user, [{"item_id": "fragile_rod"}])[0]
        repository.equip(user.id, item.slot_id)

        assert repository.consume_durability(user.id, "rod", 1) == "Fragile Rod"
        assert repository._lock_items(user.id) == []
        assert repository.get_equipped(user.id) == []
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_consumable_use_is_atomic_and_idempotent() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex
        channel = Channel(twitch_id=f"use-{suffix}", name="Use test", config={})
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id=f"user-{suffix}",
            username="use_user",
            channel_id=channel.id,
            current_mass=0,
            inventory={"max_slots": 1, "equipped_rod_slot": None},
        )
        reward = ItemDefinition(
            channel_id=channel.id,
            item_id="box_reward",
            title="Box Reward",
            type="material",
            stack_size=1,
            effects=[],
        )
        box = ItemDefinition(
            channel_id=channel.id,
            item_id="test_box",
            title="Test Box",
            type="lootbox",
            stack_size=1,
            effects=[
                {"type": "grant_item", "item_id": "box_reward", "quantity": 1},
                {"type": "grant_mass", "mass": "2.50"},
            ],
        )
        db.add_all([user, reward, box])
        db.flush()
        repository = InventoryRepository(db)
        repository.grant_many(user, [{"item_id": "test_box"}])

        first = repository.use_item(user, 1, "use-key")
        replay = repository.use_item(user, 1, "use-key")

        assert replay == first
        assert first["mass_delta"] == "2.50"
        rows = repository._lock_items(user.id)
        assert [(row.slot_id, row.definition.item_id) for row in rows] == [
            (1, "box_reward")
        ]
        assert user.current_mass == Decimal("2.50")
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_equipped_storage_expands_effective_inventory_capacity() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex
        channel = Channel(twitch_id=f"storage-{suffix}", name="Storage test", config={})
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id=f"user-{suffix}",
            username="storage_user",
            channel_id=channel.id,
            inventory={"max_slots": 1, "equipped_rod_slot": None},
        )
        storage = ItemDefinition(
            channel_id=channel.id,
            item_id="test_storage",
            title="Test Storage",
            type="equipment",
            slot="storage",
            stack_size=1,
            effects=[
                {
                    "type": "stat_add",
                    "stat": "inventory_slots_add",
                    "value": "2",
                }
            ],
        )
        material = ItemDefinition(
            channel_id=channel.id,
            item_id="storage_material",
            title="Storage Material",
            type="material",
            stack_size=1,
            effects=[],
        )
        db.add_all([user, storage, material])
        db.flush()

        base_repository = InventoryRepository(db)
        storage_item = base_repository.grant_many(user, [{"item_id": "test_storage"}])[0]
        base_repository.equip(user.id, storage_item.slot_id)
        slot_bonus = PlayerModifierService(db).inventory_slot_bonus(user)
        assert slot_bonus == 2

        expanded_repository = InventoryRepository(db, max_slots_add=slot_bonus)
        expanded_repository.grant_many(
            user, [{"item_id": "storage_material", "quantity": 2}]
        )
        assert [row.slot_id for row in expanded_repository._lock_items(user.id)] == [1, 2, 3]
        response = InventoryService(UserRepository(db)).get_inventory_msg(
            user.user_twitch_id, channel.twitch_id
        )
        assert response.max_slots == 3
    finally:
        db.rollback()
        db.close()
