"""Unit tests for fishing cast ledger completeness: flags, strict mode,
rejected statuses, replay marking, modifier persistence and roll columns."""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from core import metrics as metrics_module
from core.config import settings
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
    ledger._find_pool = lambda user: None
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
