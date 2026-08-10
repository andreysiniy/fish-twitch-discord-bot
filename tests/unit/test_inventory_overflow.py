"""Unit tests for durable inventory overflow (mailbox) parking.

Covers plan sections 9 (item XP gating) and 10 (finite-stock drops must not be
lost when the inventory is full): the engine exposes ``item_xp_gained`` and the
fishing service parks a full-inventory drop in ``inventory_overflow_items``
instead of failing the grant.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from domain.schemas.fishing import FishingResult
from infrastructure.database import Base
from services.fishing.engine import FishingEngine
from services.fishing_service import FishingService


def _user(**overrides):
    values = {
        "id": 1,
        "channel_id": 10,
        "user_twitch_id": "viewer",
        "username": "viewer",
        "current_location_id": "default",
        "xp": 0,
        "level": 1,
        "current_mass": Decimal("10"),
        "total_mass_stat": Decimal("0"),
        "total_fish_stat": 0,
        "channel": SimpleNamespace(config={}),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _item_drop(**overrides):
    values = {
        "item_id": "rare_rod",
        "item_definition_id": 42,
        "title": "Rare Rod",
        "quantity": 1,
        "quantity_requested": 1,
        "xp_gain": 50,
        "current_durability": None,
        "meta": {},
        "loot_table_entry_id": 7,
        "db_id": 7,
    }
    values.update(overrides)
    return values


def _result(**overrides):
    values = dict(
        loot={"type": "fish", "xp": 10},
        item_drop=None,
        username="viewer",
        xp_gained=10,
        item_xp_gained=0,
        mass_gained=Decimal("0"),
        is_level_up=False,
        old_level=1,
        new_level=1,
    )
    values.update(overrides)
    return FishingResult(**values)


def _service():
    service = FishingService.__new__(FishingService)
    user = _user()
    service.user_repo = Mock()
    service.user_repo.get_progress.return_value = user
    service.user_repo.apply_equipped_rod_durability_loss.return_value = None
    service.config_repo = Mock()
    service.config_repo.get_dual_pool.return_value = (
        [{"type": "nothing", "weight": 100}],
        [],
        0.0,
    )
    service.cooldown_repo = Mock()
    service.strategy_resolver = Mock()
    service.strategy_resolver.resolve.return_value = SimpleNamespace(
        calculation_strategy=None,
        override_loot_pool_location_id=None,
    )
    service.modifier_service = Mock()
    service.modifier_service.resolve.return_value = SimpleNamespace(
        values={},
        effects=[],
        mass_floor=lambda _: Decimal("0"),
        value=lambda _stat: Decimal("0"),
        explain=lambda: "",
    )
    service.modifier_service.inventory_slot_bonus.return_value = 0
    service.overflow_repo = Mock()
    service.presenter = Mock()
    service.presenter.build_response.return_value = SimpleNamespace(
        model_dump=lambda mode: {"chat_message": "ok"},
        cast_id=None,
    )
    service.ledger = Mock()
    service.ledger.find_replay.return_value = None
    service._record_resolved_cast = Mock(return_value=None)
    service._record_failed_cast = Mock()
    return service, user


def _grant_raises_capacity(*_args, **_kwargs):
    from infrastructure.repositories.inventory_repo import InventoryCapacityError

    raise InventoryCapacityError("Inventory is full")


def test_overflow_table_columns_and_constraints() -> None:
    table = Base.metadata.tables["inventory_overflow_items"]
    columns = {column.name: column for column in table.columns}
    assert {
        "id",
        "channel_id",
        "user_id",
        "item_definition_id",
        "quantity",
        "source_type",
        "source_id",
        "status",
        "version",
        "created_at",
        "claimed_at",
    } <= set(columns)
    constraints = {str(item) for item in table.constraints}
    assert any("ck_inventory_overflow_items_status" in item for item in constraints)
    assert any("fk_inventory_overflow_items_user_channel" in item for item in constraints)


def test_item_xp_gained_is_computed_and_zero_without_item() -> None:
    item_pool = [
        {
            "item_id": "rare_rod",
            "title": "Rare Rod",
            "xp_gain": 50,
            "weight": 100,
            "rarity": "rare",
            "item_type": "equipment",
            "min_quantity": 1,
            "max_quantity": 1,
            "remaining_stock": None,
            "item_definition_id": 1,
            "loot_table_entry_id": 1,
            "loot_table_id": 1,
        }
    ]
    engine = FishingEngine()
    with_item = engine.calculate_result(
        user=_user(),
        loot_pool=[{"type": "fish", "weight": 1, "xp": 10}],
        item_pool=item_pool,
        items_drop_rate=1.0,
        custom_params={},
    )
    assert with_item.item_xp_gained == 50
    assert with_item.xp_gained == 60

    without_item = engine.calculate_result(
        user=_user(),
        loot_pool=[{"type": "fish", "weight": 1, "xp": 10}],
        item_pool=[],
        items_drop_rate=0,
        custom_params={},
    )
    assert without_item.item_xp_gained == 0
    assert without_item.xp_gained == 10


def test_capacity_error_parks_overflow_and_keeps_item_xp() -> None:
    service, user = _service()
    result = _result(
        item_drop=_item_drop(),
        xp_gained=60,
        item_xp_gained=50,
        is_level_up=True,
        new_level=2,
    )
    service.engine = Mock()
    service.engine.calculate_result.return_value = result
    service.config_repo.reserve_loot_table_entry_stock.return_value = (True, 5, 4, 1)

    with patch(
        "services.fishing_service.InventoryRepository.grant_many",
        side_effect=_grant_raises_capacity,
    ):
        response = service.process_cast(
            "viewer",
            "viewer",
            "10",
            bypass_cooldown=True,
            source="twitch",
            source_request_id="cast-1",
        )

    assert result.item_drop["grant_success"] is True
    assert result.item_drop["overflowed"] is True
    assert result.item_drop["quantity"] == 1
    service.overflow_repo.park.assert_called_once_with(
        user=user,
        item_definition_id=42,
        quantity=1,
        source_type="fishing_cast",
        source_id="cast-1",
    )
    # The drop counts as delivered, so item XP is kept.
    assert result.xp_gained == 60
    assert user.xp == 60
    assert result.is_level_up is True
    assert response is not None


def test_successful_grant_does_not_park_overflow() -> None:
    service, user = _service()
    result = _result(item_drop=_item_drop(), xp_gained=60, item_xp_gained=50)
    service.engine = Mock()
    service.engine.calculate_result.return_value = result
    service.config_repo.reserve_loot_table_entry_stock.return_value = (True, 5, 4, 1)

    with patch("services.fishing_service.InventoryRepository.grant_many", return_value=[]):
        service.process_cast(
            "viewer",
            "viewer",
            "10",
            bypass_cooldown=True,
            source="twitch",
            source_request_id="cast-2",
        )

    service.overflow_repo.park.assert_not_called()
    assert result.item_drop["grant_success"] is True
    assert "overflowed" not in result.item_drop
    assert user.xp == 60


def test_failed_grant_strips_item_xp_and_recomputes_level() -> None:
    service, user = _service()
    result = _result(
        item_drop=_item_drop(item_definition_id=None),
        xp_gained=60,
        item_xp_gained=50,
        is_level_up=True,
        new_level=2,
    )
    service.engine = Mock()
    service.engine.calculate_result.return_value = result
    service.engine.calculate_level.return_value = 1
    service.config_repo.reserve_loot_table_entry_stock.return_value = (True, 5, 4, 1)

    with patch(
        "services.fishing_service.InventoryRepository.grant_many",
        side_effect=_grant_raises_capacity,
    ):
        service.process_cast(
            "viewer",
            "viewer",
            "10",
            bypass_cooldown=True,
            source="twitch",
            source_request_id="cast-3",
        )

    # No definition id -> cannot park -> grant failed -> item XP removed.
    service.overflow_repo.park.assert_not_called()
    assert result.item_drop["grant_success"] is False
    assert result.xp_gained == 10
    assert user.xp == 10
    assert result.is_level_up is False
    assert user.level == 1


def test_stock_empty_drop_strips_item_xp() -> None:
    service, user = _service()
    result = _result(item_drop=_item_drop(), xp_gained=60, item_xp_gained=50)
    service.engine = Mock()
    service.engine.calculate_result.return_value = result
    service.engine.calculate_level.return_value = 1
    # Stock reservation fails -> the drop becomes None -> no delivery.
    service.config_repo.reserve_loot_table_entry_stock.return_value = (False, 0, 0, 0)

    service.process_cast(
        "viewer",
        "viewer",
        "10",
        bypass_cooldown=True,
        source="twitch",
        source_request_id="cast-4",
    )

    assert result.item_drop is None
    assert result.xp_gained == 10
    assert user.xp == 10


def test_no_item_drop_keeps_xp_untouched() -> None:
    service, user = _service()
    result = _result(xp_gained=10, item_xp_gained=0)
    service.engine = Mock()
    service.engine.calculate_result.return_value = result

    service.process_cast(
        "viewer",
        "viewer",
        "10",
        bypass_cooldown=True,
        source="twitch",
        source_request_id="cast-5",
    )

    assert result.xp_gained == 10
    assert user.xp == 10
