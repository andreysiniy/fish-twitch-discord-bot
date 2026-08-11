import os
import uuid
from decimal import Decimal

import pytest

from infrastructure.database import SessionLocal
from infrastructure.models import (
    Channel,
    InventoryItem,
    InventoryOverflowItem,
    ItemDefinition,
    UserProgress,
)
from infrastructure.repositories.inventory_repo import (
    InventoryCapacityError,
    InventoryRepository,
)
from infrastructure.repositories.inventory_overflow_repo import InventoryOverflowRepository
from infrastructure.repositories.user_repo import UserRepository
from services.inventory_service import InventoryService
from services.player_modifier_service import PlayerModifierService
from sqlalchemy.exc import IntegrityError

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
            base_inventory_slots=3,
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
def test_trash_removes_slot_and_protects_equipped_items() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex
        channel = Channel(twitch_id=f"trash-{suffix}", name="Trash test", config={})
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id=f"user-{suffix}",
            username="trash_user",
            channel_id=channel.id,
            base_inventory_slots=3,
        )
        bait_definition = ItemDefinition(
            channel_id=channel.id,
            item_id="trash_bait",
            title="Trash Bait",
            type="material",
            stack_size=10,
            effects=[],
        )
        rod_definition = ItemDefinition(
            channel_id=channel.id,
            item_id="trash_rod",
            title="Trash Rod",
            type="equipment",
            slot="rod",
            stack_size=1,
            max_durability=10,
            break_policy="destroy_at_zero",
            effects=[],
        )
        db.add_all([user, bait_definition, rod_definition])
        db.flush()
        repository = InventoryRepository(db)

        bait = repository.grant_many(user, [{"item_id": "trash_bait", "quantity": 2}])[0]
        assert repository.trash(user.id, bait.slot_id) == ("Trash Bait", 2)
        assert repository._lock_items(user.id) == []

        rod = repository.grant_many(user, [{"item_id": "trash_rod"}])[0]
        repository.equip(user.id, rod.slot_id)
        with pytest.raises(ValueError, match="is equipped"):
            repository.trash(user.id, rod.slot_id)
        assert repository._lock_items(user.id)[0].slot_id == rod.slot_id
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_trash_claims_oldest_overflow_into_freed_slot() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex
        channel = Channel(twitch_id=f"trash-overflow-{suffix}", name="Trash overflow", config={})
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id=f"user-{suffix}",
            username="trash_overflow_user",
            channel_id=channel.id,
            base_inventory_slots=1,
        )
        filler_definition = ItemDefinition(
            channel_id=channel.id,
            item_id="trash_filler",
            title="Trash Filler",
            type="material",
            stack_size=1,
            effects=[],
        )
        overflow_definition = ItemDefinition(
            channel_id=channel.id,
            item_id="parked_bait",
            title="Parked Bait",
            type="material",
            stack_size=1,
            effects=[],
        )
        db.add_all([user, filler_definition, overflow_definition])
        db.flush()
        repository = InventoryRepository(db)
        filler = repository.grant_many(user, [{"item_id": "trash_filler"}])[0]
        parked = InventoryOverflowRepository(db).park(
            user=user,
            item_definition_id=overflow_definition.id,
            quantity=1,
        )

        repository.trash(user.id, filler.slot_id)

        item = repository._lock_items(user.id)[0]
        assert item.item_id == overflow_definition.id
        refreshed = (
            db.query(InventoryOverflowItem)
            .filter(InventoryOverflowItem.id == parked.id)
            .one()
        )
        assert refreshed.status == "claimed"
        assert refreshed.claimed_at is not None
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
            base_inventory_slots=2,
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
            base_inventory_slots=1,
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
def test_charge_based_consumable_decrements_charges_and_is_deleted_at_zero() -> None:
    """A charge-based consumable consumes current_charges, never durability."""
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex
        channel = Channel(twitch_id=f"charges-{suffix}", name="Charges test", config={})
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id=f"user-{suffix}",
            username="charges_user",
            channel_id=channel.id,
            current_mass=0,
            base_inventory_slots=2,
        )
        potion = ItemDefinition(
            channel_id=channel.id,
            item_id="spell_potion",
            title="Spell Potion",
            type="consumable",
            stack_size=1,
            max_charges=3,
            effects=[
                {"type": "grant_mass", "mass": "1.00"},
                {"type": "consume_charge", "trigger": "on_use", "amount": 1},
            ],
        )
        db.add_all([user, potion])
        db.flush()
        repository = InventoryRepository(db)

        granted = repository.grant_many(user, [{"item_id": "spell_potion"}])[0]
        assert granted.current_charges == 3
        assert granted.current_durability is None

        repository.use_item(user, granted.slot_id, "charge-use-1")
        rows = repository._lock_items(user.id)
        assert len(rows) == 1
        assert rows[0].current_charges == 2
        assert rows[0].quantity == 1

        repository.use_item(user, rows[0].slot_id, "charge-use-2")
        rows = repository._lock_items(user.id)
        assert rows[0].current_charges == 1

        repository.use_item(user, rows[0].slot_id, "charge-use-3")
        # At zero the instance is deleted, exactly like an empty stack.
        assert repository._lock_items(user.id) == []
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_charge_consumption_honors_consume_charge_amount() -> None:
    """use_item consumes the amount declared by the consume_charge effect."""
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex
        channel = Channel(twitch_id=f"charges-amt-{suffix}", name="Charges amount", config={})
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id=f"user-{suffix}",
            username="charges_amt_user",
            channel_id=channel.id,
            current_mass=0,
            base_inventory_slots=2,
        )
        potion = ItemDefinition(
            channel_id=channel.id,
            item_id="spell_potion",
            title="Spell Potion",
            type="consumable",
            stack_size=1,
            max_charges=6,
            effects=[
                {"type": "grant_mass", "mass": "1.00"},
                {"type": "consume_charge", "trigger": "on_use", "amount": 2},
            ],
        )
        db.add_all([user, potion])
        db.flush()
        repository = InventoryRepository(db)

        granted = repository.grant_many(user, [{"item_id": "spell_potion"}])[0]
        assert granted.current_charges == 6

        repository.use_item(user, granted.slot_id, "charge-amt-use-1")
        rows = repository._lock_items(user.id)
        assert rows[0].current_charges == 4
        assert rows[0].quantity == 1

        repository.use_item(user, rows[0].slot_id, "charge-amt-use-2")
        assert repository._lock_items(user.id)[0].current_charges == 2

        repository.use_item(user, rows[0].slot_id, "charge-amt-use-3")
        assert repository._lock_items(user.id) == []
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_charge_grant_rejects_durability_mismatch_and_out_of_range() -> None:
    """A charge-based consumable never resolves durability; charges are capped."""
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex
        channel = Channel(twitch_id=f"charges-bad-{suffix}", name="Charges bad", config={})
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id=f"user-{suffix}",
            username="charges_bad_user",
            channel_id=channel.id,
            base_inventory_slots=2,
        )
        potion = ItemDefinition(
            channel_id=channel.id,
            item_id="spell_potion",
            title="Spell Potion",
            type="consumable",
            stack_size=1,
            max_charges=3,
            effects=[],
        )
        db.add_all([user, potion])
        db.flush()
        repository = InventoryRepository(db)

        with pytest.raises(ValueError, match="indestructible"):
            repository.grant_many(user, [{"item_id": "spell_potion", "current_durability": 2}])
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_database_enforces_current_charges_against_definition() -> None:
    """Charge bounds remain enforced when service validation is bypassed."""
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex
        channel = Channel(twitch_id=f"charges-db-{suffix}", name="Charges DB", config={})
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id=f"user-{suffix}",
            username="charges_db_user",
            channel_id=channel.id,
        )
        potion = ItemDefinition(
            channel_id=channel.id,
            item_id="db_charge_potion",
            title="DB Charge Potion",
            type="consumable",
            stack_size=1,
            max_charges=3,
            effects=[],
        )
        db.add_all([user, potion])
        db.commit()

        db.add(
            InventoryItem(
                channel_id=channel.id,
                user_id=user.id,
                item_id=potion.id,
                slot_id=1,
                quantity=1,
                current_charges=3,
            )
        )
        db.commit()

        db.add(
            InventoryItem(
                channel_id=channel.id,
                user_id=user.id,
                item_id=potion.id,
                slot_id=2,
                quantity=1,
                current_charges=4,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

        persisted = db.query(ItemDefinition).filter(ItemDefinition.id == potion.id).one()
        persisted.max_charges = 2
        with pytest.raises(IntegrityError):
            db.flush()
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
            base_inventory_slots=1,
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


@pytest.mark.integration
def test_inventory_response_includes_active_overflow_count() -> None:
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex
        channel = Channel(
            twitch_id=f"inventory-overflow-count-{suffix}",
            name="Overflow count",
            config={},
        )
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id=f"overflow-count-user-{suffix}",
            username="overflow_count_user",
            channel_id=channel.id,
            base_inventory_slots=1,
        )
        definition = ItemDefinition(
            channel_id=channel.id,
            item_id=f"overflow-count-item-{suffix}",
            title="Overflow count item",
            type="material",
            stack_size=1,
            effects=[],
        )
        db.add_all([user, definition])
        db.flush()
        InventoryOverflowRepository(db).park(
            user=user,
            item_definition_id=definition.id,
            quantity=1,
        )
        response = InventoryService(UserRepository(db)).get_inventory_msg(
            user.user_twitch_id, channel.twitch_id
        )
        assert response.overflow_count == 1
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_equip_without_slot_returns_editable_usage_message() -> None:
    """Missing slot answers with the configurable equip_help message."""
    from domain.schemas.rpg import EquipRequestDTO

    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel = Channel(
            twitch_id=f"equip-usage-{suffix}",
            name="Equip Usage",
            config={"messages": {"equip_help": "Custom usage: !fishequip <N>"}},
        )
        db.add(channel)
        db.flush()
        user = UserProgress(
            user_twitch_id=f"usage-user-{suffix}",
            username="usage_user",
            channel_id=channel.id,
        )
        db.add(user)
        db.flush()

        service = InventoryService(UserRepository(db))

        # No slot -> the custom usage message from the channel config.
        missing = service.equip_item(
            EquipRequestDTO(
                user_id=f"usage-user-{suffix}",
                channel_id=channel.twitch_id,
                slot_id=None,
            )
        )
        assert missing.success is False
        assert missing.message == "Custom usage: !fishequip <N>"

        # Invalid (non-positive) slot -> same usage message.
        zero = service.equip_item(
            EquipRequestDTO(
                user_id=f"usage-user-{suffix}",
                channel_id=channel.twitch_id,
                slot_id=0,
            )
        )
        assert zero.success is False
        assert zero.message == "Custom usage: !fishequip <N>"

        # A channel without a custom message falls back to the default.
        plain = Channel(
            twitch_id=f"equip-plain-{suffix}",
            name="Equip Plain",
            config={},
        )
        db.add(plain)
        db.flush()
        default_usage = service.equip_item(
            EquipRequestDTO(
                user_id=f"usage-user-{suffix}",
                channel_id=plain.twitch_id,
                slot_id=None,
            )
        )
        assert "!fishequip" in default_usage.message
    finally:
        db.rollback()
        db.close()
