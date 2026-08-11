"""Unit tests for fishing cast ledger completeness: flags, strict mode,
rejected statuses, replay marking, modifier persistence and roll columns."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from core import metrics as metrics_module
from core.config import settings
from domain.logic.loot_selection import ItemDropResolution
from domain.schemas.fishing import FishingResult
from services.fishing.ledger_service import (
    CAST_STATUS_COOLDOWN_REJECTED,
    CAST_STATUS_VALIDATION_REJECTED,
    FishingLedgerService,
)
from services.fishing_service import FishingService


def _user(**overrides):
    values = {
        "id": 7,
        "channel_id": 3,
        "user_twitch_id": "viewer",
        "username": "viewer",
        "current_mass": Decimal("100.00"),
        "total_mass_stat": Decimal("100.00"),
        "xp": 100,
        "level": 2,
        "current_location_id": "lake",
        "channel": SimpleNamespace(config_version=2, config={}),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _result(**overrides):
    values = {
        "loot": {"type": "fish", "weight": 1, "identifier": "r1", "percentage": "0.1"},
        "item_drop": None,
        "username": "viewer",
        "xp_gained": 10,
        "mass_gained": Decimal("5.00"),
        "is_level_up": False,
        "old_level": 2,
        "new_level": 2,
        "fish_luck_factor_used": Decimal("1.4"),
        "positive_fish_factor_used": Decimal("1.05"),
        "negative_fish_factor_used": Decimal("0.95"),
        "effective_percentage": Decimal("0.147"),
        "item_drop_probability": Decimal("0.30"),
        "item_drop_roll": Decimal("0.10"),
        "reward_roll_trace": {
            "selected_id": "r1",
            "roll": "0.25",
            "total_weight": "100",
            "selected_weight": "20",
            "selected_probability": "0.2",
        },
        "rng_stages": [],
        "robbery_result": None,
        "roulette_result": None,
    }
    values.update(overrides)
    return FishingResult(**values)


class _Repo:
    def __init__(self):
        self.casts = []

    def create_cast(self, **fields):
        cast = SimpleNamespace(**fields)
        cast.id = f"cast-{len(self.casts)}"
        self.casts.append(cast)
        return cast

    def add_item_drop(self, **fields):
        return None


class _Ledger:
    def __init__(self):
        self.recorded = []

    def find_replay(self, channel_id, source, source_request_id):
        return None

    def record_rejected(self, **kwargs):
        self.recorded.append(("rejected", kwargs))

    def record_resolved(self, **kwargs):
        self.recorded.append(("resolved", kwargs))
        return SimpleNamespace(id="cast-uuid", response_snapshot={})


def _service(ledger=None):
    service = MagicMock(spec=FishingService)
    service.ledger = ledger or _Ledger()
    service.strategy_resolver = MagicMock()
    service.strategy_resolver.channel_repo.get_active_fishing_event.return_value = None
    return service


def test_replay_response_is_marked_and_metrics_inc(monkeypatch) -> None:
    from domain.schemas.fishing import FishResponse

    ledger = _Ledger()
    ledger.find_replay = lambda c, s, rid: SimpleNamespace(
        response_snapshot=FishResponse(chat_message="hi", xp_gained=0).model_dump(mode="json")
    )
    service = FishingService.__new__(FishingService)
    service.ledger = ledger
    service.user_repo = MagicMock()
    service.user_repo.get_progress.return_value = _user()
    service.presenter = MagicMock()
    metrics_module.reset()
    response = service.process_cast("viewer", "viewer", "3", source="twitch", source_request_id="m1")
    assert response.is_replayed is True
    assert metrics_module.snapshot().get("fishing_duplicate_requests_total") == 1


def test_cooldown_rejected_cast_is_recorded(monkeypatch) -> None:
    ledger = _Ledger()
    service = FishingService.__new__(FishingService)
    service.ledger = ledger
    service.user_repo = MagicMock()
    service.user_repo.get_progress.return_value = _user()
    service.strategy_resolver = MagicMock()
    service.modifier_service = MagicMock()
    service.modifier_service.resolve.return_value = SimpleNamespace(
        value=lambda stat: Decimal("0")
    )
    service.cooldown_repo = MagicMock()
    service.cooldown_repo.check_cooldown.return_value = (True, 42)
    service.presenter = MagicMock()
    service.presenter.build_cooldown_response.return_value = "cooldown"

    monkeypatch.setattr(settings, "FISHING_CAST_LEDGER_ENABLED", True)
    result = service.process_cast(
        "viewer", "viewer", "3", source="twitch", source_request_id="m2"
    )
    assert result == "cooldown"
    assert ledger.recorded
    assert ledger.recorded[0][0] == "rejected"
    assert ledger.recorded[0][1]["status"] == CAST_STATUS_COOLDOWN_REJECTED


def test_ledger_disabled_skips_recording(monkeypatch) -> None:
    ledger = _Ledger()
    service = FishingService.__new__(FishingService)
    service.ledger = ledger
    service.user_repo = MagicMock()
    service.user_repo.get_progress.return_value = _user()
    service.strategy_resolver = MagicMock()
    monkeypatch.setattr(settings, "FISHING_CAST_LEDGER_ENABLED", False)
    cast = service._record_resolved_cast(
        user=_user(),
        result=_result(),
        custom_params={},
        is_mod=False,
        is_sub=False,
        bypass_cooldown=False,
        cooldown_duration=0,
        source="twitch",
        source_request_id="m3",
    )
    assert cast is None
    assert ledger.recorded == []


def test_strict_mode_raises_on_ledger_failure(monkeypatch) -> None:
    class BrokenLedger(_Ledger):
        def record_resolved(self, **kwargs):
            raise RuntimeError("db down")

    service = FishingService.__new__(FishingService)
    service.ledger = BrokenLedger()
    service.user_repo = MagicMock()
    service.user_repo.get_progress.return_value = _user()
    service.strategy_resolver = MagicMock()
    service.strategy_resolver.channel_repo.get_active_fishing_event.return_value = None
    service.cooldown_repo = MagicMock()
    service.cooldown_repo.next_available_at.return_value = None
    monkeypatch.setattr(settings, "FISHING_CAST_LEDGER_ENABLED", True)
    monkeypatch.setattr(settings, "FISHING_CAST_LEDGER_STRICT", True)
    with pytest.raises(RuntimeError):
        service._record_resolved_cast(
            user=_user(),
            result=_result(),
            custom_params={},
            is_mod=False,
            is_sub=False,
            bypass_cooldown=False,
            cooldown_duration=0,
            source="twitch",
            source_request_id="m4",
        )


def test_record_resolved_persists_modifiers_and_roll_columns() -> None:
    repo = _Repo()
    ledger = FishingLedgerService.__new__(FishingLedgerService)
    ledger.repo = repo
    ledger.db = MagicMock()
    ledger._find_pool = lambda user, location_id=None: None
    ledger.get_or_create_ruleset_snapshot = lambda **kw: ("snap-1", True)
    result = _result()
    cast = ledger.record_resolved(
        user=_user(),
        result=result,
        channel_config_version=2,
        event_snapshot={},
        effective_params_snapshot={},
        engine_version="test",
        source="twitch",
        source_request_id="m5",
        modifier_explanation={
            "fish_luck_change_ratio": {
                "value": "0.40",
                "raw": "0.40",
                "sources": [{"type": "event", "id": "17", "value": "0.40"}],
            }
        },
        triggered_effects=[{"type": "mass_floor", "protected_mass": "10"}],
        item_entries=[{"item_id": "x", "weight": 1}],
        items_drop_rate=0.3,
        item_loot_table_id=5,
        item_loot_table_version=1,
        duration_ms=12,
    )
    assert cast.reward_roll == Decimal("0.25")
    assert cast.reward_total_weight == Decimal("100")
    assert cast.reward_probability == Decimal("0.2")
    assert cast.reward_weight == Decimal("20")
    assert cast.item_drop_probability == Decimal("0.30")
    assert cast.item_drop_roll == Decimal("0.10")
    assert cast.resolved_modifiers["fish_luck_change_ratio"] == "0.40"
    assert cast.modifier_sources["fish_luck_change_ratio"]["sources"][0]["type"] == "event"
    assert cast.triggered_effects[0]["type"] == "mass_floor"
    assert cast.duration_ms == 12
    assert cast.requested_at is not None


def test_record_rejected_keeps_no_rng_state() -> None:
    repo = _Repo()
    ledger = FishingLedgerService.__new__(FishingLedgerService)
    ledger.repo = repo
    ledger.db = MagicMock()
    cast = ledger.record_rejected(
        channel_id=3,
        user_progress_id=7,
        twitch_user_id="viewer",
        username="viewer",
        location_id="lake",
        status=CAST_STATUS_VALIDATION_REJECTED,
        error_code="BAD_INPUT",
        source="twitch",
        source_request_id="m6",
    )
    assert cast.status == CAST_STATUS_VALIDATION_REJECTED
    assert cast.error_code == "BAD_INPUT"
    assert cast.source_request_id == "m6"
    assert not hasattr(cast, "reward_roll") or cast.reward_roll is None


def test_record_resolved_snapshots_the_whole_pool_and_actual_pool_location() -> None:
    """The ruleset snapshot gets the full reward pool, not just the winner."""
    ledger = FishingLedgerService(db=MagicMock())
    ledger.repo = MagicMock()
    ledger._find_pool = MagicMock(return_value=SimpleNamespace(
        id=9, version=3, location_name="river"
    ))
    captured: dict = {}
    ledger.get_or_create_ruleset_snapshot = lambda **kw: (
        captured.update(kw) or ("snap-1", True)
    )
    pool_entries = [
        {"reward_id": "r1", "type": "nothing", "weight": 90},
        {"reward_id": "r2", "type": "fish", "weight": 10},
    ]
    result = _result(rng_stages=[])
    ledger.repo.create_cast.return_value = SimpleNamespace(id="cast-1", channel_id=3)

    ledger.record_resolved(
        user=_user(),
        result=result,
        channel_config_version=2,
        event_snapshot={},
        effective_params_snapshot={},
        engine_version="2.1.0",
        source_request_id="req-1",
        loot_pool=pool_entries,
        pool_location_id="river",
    )

    assert captured["rewards"] == pool_entries
    assert captured["pool"].id == 9
    assert ledger._find_pool.call_args.args[1] == "river"


def test_record_resolved_uses_reward_id_and_points_delta() -> None:
    ledger = FishingLedgerService(db=MagicMock())
    ledger.repo = MagicMock()
    ledger._find_pool = lambda user, location_id=None: None
    ledger.get_or_create_ruleset_snapshot = lambda **kw: ("snap-1", True)
    result = _result(
        loot={"type": "points", "reward_id": "p1", "value": 42},
        rng_stages=[],
    )
    ledger.repo.create_cast.return_value = SimpleNamespace(id="cast-1", channel_id=3)

    ledger.record_resolved(
        user=_user(),
        result=result,
        channel_config_version=2,
        event_snapshot={},
        effective_params_snapshot={},
        engine_version="2.1.0",
        source_request_id="req-1",
        loot_pool=[result.loot],
    )

    assert ledger.repo.create_cast.call_args.kwargs["points_delta"] == 42
    assert ledger.repo.create_cast.call_args.kwargs["reward_id"] == "p1"


def test_record_resolved_fills_item_drop_subflags_and_selection_trace() -> None:
    ledger = FishingLedgerService(db=MagicMock())
    ledger.repo = MagicMock()
    ledger._find_pool = lambda user, location_id=None: None
    ledger.get_or_create_ruleset_snapshot = lambda **kw: ("snap-1", True)
    result = _result(
        loot={"type": "fish", "reward_id": "r1"},
        item_drop={
            "item_id": "rod",
            "title": "Rod",
            "item_definition_id": 5,
            "quantity": 2,
            "stock_reserved": True,
            "grant_success": True,
        },
        rng_stages=[
            {"stage": "item_drop_gate", "roll": "0.1", "threshold": "0.3", "success": True},
            {
                "stage": "item_selection",
                "roll": "0.5",
                "total_weight": "10",
                "selected_weight": "4",
                "selected_probability": "0.4",
            },
        ],
    )
    ledger.repo.create_cast.return_value = SimpleNamespace(id="cast-1", channel_id=3)

    ledger.record_resolved(
        user=_user(),
        result=result,
        channel_config_version=2,
        event_snapshot={},
        effective_params_snapshot={},
        engine_version="2.1.0",
        source_request_id="req-1",
        loot_pool=[result.loot],
    )

    cast_kwargs = ledger.repo.create_cast.call_args.kwargs
    assert cast_kwargs["item_drop_gate_success"] is True
    assert cast_kwargs["item_drop_selection_success"] is True
    assert cast_kwargs["item_drop_stock_reserved"] is True
    assert cast_kwargs["item_drop_grant_success"] is True
    drop_kwargs = ledger.repo.add_item_drop.call_args.kwargs
    assert drop_kwargs["selection_roll"] == Decimal("0.5")
    assert drop_kwargs["selection_total_weight"] == Decimal("10")
    assert drop_kwargs["selection_probability"] == Decimal("0.4")
    assert drop_kwargs["quantity_requested"] == 2
    assert drop_kwargs["quantity_granted"] == 2
    assert drop_kwargs["grant_status"] == "granted"


def test_record_resolved_marks_failed_grant_when_inventory_full() -> None:
    ledger = FishingLedgerService(db=MagicMock())
    ledger.repo = MagicMock()
    ledger._find_pool = lambda user, location_id=None: None
    ledger.get_or_create_ruleset_snapshot = lambda **kw: ("snap-1", True)
    result = _result(
        loot={"type": "fish", "reward_id": "r1"},
        item_drop={
            "item_id": "rod",
            "title": "Rod",
            "item_definition_id": 5,
            "quantity": 1,
            "stock_reserved": True,
            "grant_success": False,
        },
        rng_stages=[
            {"stage": "item_drop_gate", "roll": "0.1", "threshold": "0.3", "success": True}
        ],
    )
    ledger.repo.create_cast.return_value = SimpleNamespace(id="cast-1", channel_id=3)

    ledger.record_resolved(
        user=_user(),
        result=result,
        channel_config_version=2,
        event_snapshot={},
        effective_params_snapshot={},
        engine_version="2.1.0",
        source_request_id="req-1",
        loot_pool=[result.loot],
    )

    drop_kwargs = ledger.repo.add_item_drop.call_args.kwargs
    assert drop_kwargs["grant_status"] == "failed"
    assert drop_kwargs["quantity_granted"] == 0
    cast_kwargs = ledger.repo.create_cast.call_args.kwargs
    assert cast_kwargs["item_drop_grant_success"] is False


def test_record_resolved_serializes_typed_drop_after_delivery() -> None:
    ledger = FishingLedgerService(db=MagicMock())
    ledger.repo = MagicMock()
    ledger._find_pool = lambda user, location_id=None: None
    ledger.get_or_create_ruleset_snapshot = lambda **kw: ("snap-1", True)
    resolution = ItemDropResolution(
        loot_table_id=12,
        loot_entry_id=34,
        item_definition_id=5,
        item_id="rod",
        title="Rod",
        selected_weight=Decimal("4"),
        total_weight=Decimal("10"),
        selection_probability=Decimal("0.4"),
        selection_roll=Decimal("0.5"),
        quantity_rolled=2,
        quantity_requested=2,
        stock_before=5,
        stock_after=3,
        quantity_granted=2,
        inventory_grants=[{"slot_id": 3, "quantity": 2}],
        delivery_target="inventory",
        status="granted",
    )
    result = _result(item_drop=None, item_drop_resolution=resolution)
    ledger.repo.create_cast.return_value = SimpleNamespace(id="cast-1", channel_id=3)

    ledger.record_resolved(
        user=_user(),
        result=result,
        channel_config_version=2,
        event_snapshot={},
        effective_params_snapshot={},
        engine_version="2.1.0",
        source_request_id="req-typed",
        loot_pool=[result.loot],
    )

    drop_kwargs = ledger.repo.add_item_drop.call_args.kwargs
    assert drop_kwargs["selection_total_weight"] == Decimal("10")
    assert drop_kwargs["inventory_grants"] == [{"slot_id": 3, "quantity": 2}]
    assert drop_kwargs["grant_status"] == "granted"


def test_record_resolved_tracks_gate_failure_without_counting_a_drop() -> None:
    ledger = FishingLedgerService(db=MagicMock())
    ledger.repo = MagicMock()
    ledger._find_pool = lambda user, location_id=None: None
    ledger.get_or_create_ruleset_snapshot = lambda **kw: ("snap-1", True)
    result = _result(
        item_drop=None,
        item_drop_resolution=ItemDropResolution(
            status="gate_failed",
            gate_success=False,
            selection_success=False,
            failure_reason="item drop gate failed",
        ),
    )
    ledger.repo.create_cast.return_value = SimpleNamespace(id="cast-1", channel_id=3)

    ledger.record_resolved(
        user=_user(),
        result=result,
        channel_config_version=2,
        event_snapshot={},
        effective_params_snapshot={},
        engine_version="2.1.0",
        source_request_id="req-gate-failed",
        loot_pool=[result.loot],
    )

    cast_kwargs = ledger.repo.create_cast.call_args.kwargs
    assert cast_kwargs["item_drop_count"] == 0
    assert cast_kwargs["item_drop_gate_success"] is False
    assert cast_kwargs["item_drop_selection_success"] is False
    assert ledger.repo.add_item_drop.call_args.kwargs["grant_status"] == "gate_failed"


def test_record_resolved_tracks_stock_empty_selection_without_delivery_count() -> None:
    ledger = FishingLedgerService(db=MagicMock())
    ledger.repo = MagicMock()
    ledger._find_pool = lambda user, location_id=None: None
    ledger.get_or_create_ruleset_snapshot = lambda **kw: ("snap-1", True)
    result = _result(
        item_drop=None,
        item_drop_resolution=ItemDropResolution(
            item_id="bait",
            status="stock_empty",
            gate_success=True,
            selection_success=True,
            stock_reserved=False,
            failure_reason="entry stock exhausted",
        ),
    )
    ledger.repo.create_cast.return_value = SimpleNamespace(id="cast-1", channel_id=3)

    ledger.record_resolved(
        user=_user(),
        result=result,
        channel_config_version=2,
        event_snapshot={},
        effective_params_snapshot={},
        engine_version="2.1.0",
        source_request_id="req-stock-empty",
        loot_pool=[result.loot],
    )

    assert ledger.repo.create_cast.call_args.kwargs["item_drop_count"] == 0
    assert ledger.repo.create_cast.call_args.kwargs["item_drop_selection_success"] is True
    assert ledger.repo.add_item_drop.call_args.kwargs["grant_status"] == "stock_empty"
