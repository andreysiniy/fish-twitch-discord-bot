"""Unit tests for deferred after-commit cooldown cache writes.

Plan section 16: the fishing cooldown cache (Redis) must only be written after
the PostgreSQL transaction commits, so a rolled-back cast can never leave
Redis-only gameplay state for a cast that never became durable.
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from domain.schemas.fishing import FishingResult
from infrastructure.after_commit import (
    run_after_commit_callbacks,
    schedule_after_commit,
)
from services.fishing_service import FishingService


def test_schedule_and_run_callbacks_after_commit() -> None:
    db = SimpleNamespace(info={})
    calls: list[int] = []

    assert schedule_after_commit(db, lambda: calls.append(1)) is True
    assert schedule_after_commit(db, lambda: calls.append(2)) is True

    run_after_commit_callbacks(db)

    assert calls == [1, 2]
    assert db.info == {}


def test_rollback_never_runs_callbacks() -> None:
    db = SimpleNamespace(info={})
    calls: list[int] = []

    schedule_after_commit(db, lambda: calls.append(1))

    # A failed transaction never reaches run_after_commit_callbacks, so the
    # scheduled cache write simply does not happen.
    assert calls == []
    assert db.info["after_commit_callbacks"]


def test_session_without_info_dict_returns_false() -> None:
    assert schedule_after_commit(SimpleNamespace(), lambda: None) is False


def test_mock_session_returns_false() -> None:
    assert schedule_after_commit(Mock(), lambda: None) is False


def test_callback_failure_does_not_block_remaining_callbacks() -> None:
    db = SimpleNamespace(info={})
    calls: list[int] = []

    def _boom() -> None:
        raise RuntimeError("cache down")

    schedule_after_commit(db, _boom)
    schedule_after_commit(db, lambda: calls.append(1))

    run_after_commit_callbacks(db)

    assert calls == [1]
    assert db.info == {}


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
        "total_mass_stat": Decimal("10"),
        "total_fish_stat": 0,
        "channel": SimpleNamespace(config={}, config_version=1),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _service():
    service = FishingService.__new__(FishingService)
    user = _user()
    service.user_repo = Mock()
    service.user_repo.get_progress.return_value = user
    service.user_repo.apply_equipped_rod_durability_loss.return_value = None
    service.user_repo.db = SimpleNamespace(info={})
    service.config_repo = Mock()
    service.config_repo.get_dual_pool.return_value = (
        [{"type": "fish", "weight": 100, "xp": 10}],
        [],
        0.0,
    )
    service.cooldown_repo = Mock()
    service.cooldown_repo.check_cooldown.return_value = (False, 0)
    service.strategy_resolver = Mock()
    service.strategy_resolver.resolve.return_value = SimpleNamespace(
        calculation_strategy=None,
        override_loot_pool_location_id=None,
    )
    service.modifier_service = Mock()
    service.modifier_service.resolve.return_value = SimpleNamespace(
        values={},
        effects=[],
        mass_floor=lambda _scope: Decimal("0"),
        value=lambda _stat: Decimal("0"),
        explain=lambda: {},
    )
    service.presenter = Mock()
    service.presenter.build_response.return_value = SimpleNamespace(
        model_dump=lambda mode: {"chat_message": "ok"},
        cast_id=None,
    )
    service.ledger = Mock()
    service.ledger.find_replay.return_value = None
    service._record_resolved_cast = Mock(return_value=None)
    service._record_failed_cast = Mock()
    service.engine = Mock()
    service.engine.calculate_result.return_value = FishingResult(
        loot={"type": "fish", "xp": 10},
        item_drop=None,
        username="viewer",
        xp_gained=10,
        mass_gained=Decimal("0"),
        is_level_up=False,
        old_level=1,
        new_level=1,
    )
    return service, user


def test_cast_registers_cooldown_write_but_defers_until_commit() -> None:
    service, user = _service()

    service.process_cast(
        "viewer",
        "viewer",
        "10",
        source="twitch",
        source_request_id="cast-cd-1",
    )

    # The cast body must not write the cooldown cache while the PostgreSQL
    # transaction is still uncommitted.
    service.cooldown_repo.set_cooldown.assert_not_called()
    # The write is deferred on the session's after-commit hook list.
    assert len(service.user_repo.db.info["after_commit_callbacks"]) == 1

    # Simulate the session dependency committing successfully.
    run_after_commit_callbacks(service.user_repo.db)

    service.cooldown_repo.set_cooldown.assert_called_once_with("10", "viewer", 600)


def test_no_after_commit_hook_skips_cooldown_cache_write() -> None:
    service, user = _service()
    service.user_repo.db = SimpleNamespace()

    service.process_cast(
        "viewer",
        "viewer",
        "10",
        source="twitch",
        source_request_id="cast-cd-2",
    )

    # Without a transaction wrapper there is nothing to guarantee the cast
    # commits, so the cache write must not happen eagerly.
    service.cooldown_repo.set_cooldown.assert_not_called()
