from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from domain.schemas.fishing import RobberyResultDTO
from services.fishing_service import FishingService


def make_user(user_id: int, name: str, twitch_id: str, mass: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        channel=SimpleNamespace(id=1, config={}),
        username=name,
        user_twitch_id=twitch_id,
        current_mass=Decimal(mass),
        total_mass_stat=Decimal(mass),
    )


def make_modifiers(effects: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        effects=effects,
        values={},
        value=lambda _key: Decimal("0"),
        mass_floor=lambda _scope: Decimal("0"),
    )


def make_defense_service(attacker, victim, engine_result, victim_effects) -> FishingService:
    service = object.__new__(FishingService)
    user_repo = Mock()
    user_repo.get_rich_victim.return_value = victim
    user_repo.lock_users.return_value = {attacker.id: attacker, victim.id: victim}
    service.user_repo = user_repo
    service.modifier_service = Mock()
    service.modifier_service.resolve.side_effect = [
        make_modifiers([]),
        make_modifiers(victim_effects),
    ]
    engine = Mock()
    engine.calculate_mass_robbery.return_value = engine_result
    service.engine = engine
    return service


def make_engine_result(success: bool) -> RobberyResultDTO:
    return RobberyResultDTO(
        is_success=success,
        amount_stolen=Decimal("10") if success else Decimal("0"),
        victim_name="victim",
        victim_twitch_id="vic",
        victim_new_mass=Decimal("90") if success else Decimal("100"),
        chance_used=0.5,
    )


def test_attempt_counter_runs_before_roll_on_failed_robbery(monkeypatch) -> None:
    monkeypatch.setattr("services.fishing_service.random.random", lambda: 0.05)
    consume = Mock()
    monkeypatch.setattr("services.fishing_service.InventoryRepository.consume_durability", consume)
    attacker = make_user(1, "attacker", "atk", "10")
    victim = make_user(2, "victim", "vic", "100")
    service = make_defense_service(
        attacker,
        victim,
        make_engine_result(success=False),
        [
            {
                "type": "robbery_counter",
                "trigger": "on_robbery_attempt",
                "chance": "1",
                "durability_cost": 1,
                "source_slot": "defense",
                "action": {"type": "timeout", "duration_seconds": 30},
            }
        ],
    )

    result = service._handle_robbery({"range": 3}, attacker, [])

    assert result.is_success is False
    assert result.counter_actions == [
        {
            "type": "timeout",
            "duration_seconds": 30,
            "reason": "Robbery counter",
            "message": "",
        }
    ]
    consume.assert_called_once_with(2, "defense", 1)


def test_success_triggered_counter_skipped_when_robbery_fails(monkeypatch) -> None:
    monkeypatch.setattr("services.fishing_service.random.random", lambda: 0.05)
    consume = Mock()
    monkeypatch.setattr("services.fishing_service.InventoryRepository.consume_durability", consume)
    attacker = make_user(1, "attacker", "atk", "10")
    victim = make_user(2, "victim", "vic", "100")
    service = make_defense_service(
        attacker,
        victim,
        make_engine_result(success=False),
        [
            {
                "type": "robbery_counter",
                "trigger": "on_robbery_success",
                "chance": "1",
                "durability_cost": 1,
                "source_slot": "counter",
                "action": {"type": "timeout", "duration_seconds": 30},
            }
        ],
    )

    result = service._handle_robbery({"range": 3}, attacker, [])

    assert result.is_success is False
    assert result.counter_actions == []
    consume.assert_not_called()


def test_success_triggered_counter_runs_after_success_decision(monkeypatch) -> None:
    monkeypatch.setattr("services.fishing_service.random.random", lambda: 0.05)
    consume = Mock()
    monkeypatch.setattr("services.fishing_service.InventoryRepository.consume_durability", consume)
    attacker = make_user(1, "attacker", "atk", "10")
    victim = make_user(2, "victim", "vic", "100")
    service = make_defense_service(
        attacker,
        victim,
        make_engine_result(success=True),
        [
            {
                "type": "robbery_counter",
                "trigger": "on_robbery_success",
                "chance": "1",
                "durability_cost": 1,
                "source_slot": "counter",
                "action": {"type": "timeout", "duration_seconds": 30},
            }
        ],
    )

    result = service._handle_robbery({"range": 3}, attacker, [])

    assert result.is_success is True
    assert result.counter_actions == [
        {
            "type": "timeout",
            "duration_seconds": 30,
            "reason": "Robbery counter",
            "message": "",
        }
    ]
    consume.assert_called_once_with(2, "counter", 1)
    assert attacker.current_mass == Decimal("20")
    assert victim.current_mass == Decimal("90")
    service.user_repo.save_progress.assert_called_once_with(victim)


def test_successful_robbery_syncs_locked_attacker_mass_to_caller() -> None:
    caller_attacker = make_user(1, "attacker", "atk", "10")
    locked_attacker = make_user(1, "attacker", "atk", "10")
    victim = make_user(2, "victim", "vic", "100")
    service = make_defense_service(
        locked_attacker,
        victim,
        make_engine_result(success=True),
        [],
    )

    service.user_repo.lock_users.return_value = {
        locked_attacker.id: locked_attacker,
        victim.id: victim,
    }

    result = service._handle_robbery({"range": 3}, caller_attacker, [])

    assert result.is_success is True
    assert locked_attacker.current_mass == Decimal("20")
    assert caller_attacker.current_mass == Decimal("20")
    assert caller_attacker.total_mass_stat == Decimal("20")


def test_absorb_returns_before_success_phase(monkeypatch) -> None:
    monkeypatch.setattr("services.fishing_service.random.random", lambda: 0.05)
    consume = Mock()
    monkeypatch.setattr("services.fishing_service.InventoryRepository.consume_durability", consume)
    attacker = make_user(1, "attacker", "atk", "10")
    victim = make_user(2, "victim", "vic", "100")
    service = make_defense_service(
        attacker,
        victim,
        make_engine_result(success=True),
        [
            {
                "type": "absorb_robbery",
                "trigger": "on_robbery_attempt",
                "chance": "1",
                "durability_cost": 1,
                "source_slot": "shield",
                "attacker_mass_delta": "0",
            },
            {
                "type": "robbery_counter",
                "trigger": "on_robbery_success",
                "chance": "1",
                "durability_cost": 1,
                "source_slot": "counter",
                "action": {"type": "timeout", "duration_seconds": 30},
            },
        ],
    )

    result = service._handle_robbery({"range": 3}, attacker, [])

    assert result.absorbed is True
    assert result.is_success is False
    assert result.counter_actions == []
    service.engine.calculate_mass_robbery.assert_not_called()
    consume.assert_called_once_with(2, "shield", 1)


def test_terminal_defense_stops_later_defenses(monkeypatch) -> None:
    service = object.__new__(FishingService)
    service.user_repo = Mock()
    service.user_repo.db = Mock()
    monkeypatch.setattr("services.fishing_service.random.random", lambda: 0.05)
    consume = Mock()
    monkeypatch.setattr("services.fishing_service.InventoryRepository.consume_durability", consume)
    attacker = SimpleNamespace(current_mass=Decimal("10"))
    victim = SimpleNamespace(id=2, current_mass=Decimal("100"))

    actions, absorbed = service._apply_robbery_defenses(
        attacker,
        victim,
        [
            {
                "type": "absorb_robbery",
                "chance": "1",
                "durability_cost": 1,
                "source_slot": "shield",
                "attacker_mass_delta": "0",
            },
            {
                "type": "robbery_counter",
                "chance": "1",
                "durability_cost": 1,
                "source_slot": "counter",
                "action": {"type": "timeout", "duration_seconds": 30},
            },
            {
                "type": "absorb_robbery",
                "chance": "1",
                "durability_cost": 1,
                "source_slot": "shield2",
                "attacker_mass_delta": "-5",
            },
        ],
    )

    assert absorbed is True
    assert actions == []
    consume.assert_called_once_with(2, "shield", 1)


def test_counter_runs_before_terminal_defense(monkeypatch) -> None:
    service = object.__new__(FishingService)
    service.user_repo = Mock()
    service.user_repo.db = Mock()
    monkeypatch.setattr("services.fishing_service.random.random", lambda: 0.05)
    consume = Mock()
    monkeypatch.setattr("services.fishing_service.InventoryRepository.consume_durability", consume)
    attacker = SimpleNamespace(current_mass=Decimal("10"))
    victim = SimpleNamespace(id=2, current_mass=Decimal("100"))

    actions, absorbed = service._apply_robbery_defenses(
        attacker,
        victim,
        [
            {
                "type": "robbery_counter",
                "chance": "1",
                "durability_cost": 1,
                "source_slot": "counter",
                "action": {"type": "timeout", "duration_seconds": 30},
            },
            {
                "type": "absorb_robbery",
                "chance": "1",
                "durability_cost": 1,
                "source_slot": "shield",
                "attacker_mass_delta": "0",
            },
        ],
    )

    assert absorbed is True
    assert actions == [
        {
            "type": "timeout",
            "duration_seconds": 30,
            "reason": "Robbery counter",
            "message": "",
        }
    ]
    assert consume.call_count == 2


def test_after_reward_roll_block_action_not_a_robbery_defense(monkeypatch) -> None:
    service = object.__new__(FishingService)
    service.user_repo = Mock()
    service.user_repo.db = Mock()
    monkeypatch.setattr("services.fishing_service.random.random", lambda: 0.05)
    consume = Mock()
    monkeypatch.setattr("services.fishing_service.InventoryRepository.consume_durability", consume)
    attacker = SimpleNamespace(current_mass=Decimal("10"))
    victim = SimpleNamespace(id=2, current_mass=Decimal("100"))

    actions, absorbed = service._apply_robbery_defenses(
        attacker,
        victim,
        [
            {
                "type": "block_action",
                "trigger": "after_reward_roll",
                "target_action_types": ["robbery"],
                "chance": "1",
                "durability_cost": 1,
            }
        ],
    )

    assert absorbed is False
    assert actions == []
    consume.assert_not_called()


def test_defense_gate_records_phase(monkeypatch) -> None:
    service = object.__new__(FishingService)
    service.user_repo = Mock()
    service.user_repo.db = Mock()
    monkeypatch.setattr("services.fishing_service.random.random", lambda: 0.05)
    attacker = SimpleNamespace(current_mass=Decimal("10"))
    victim = SimpleNamespace(id=2, current_mass=Decimal("100"))
    stages: list = []

    service._apply_robbery_defenses(
        attacker,
        victim,
        [
            {
                "type": "robbery_counter",
                "chance": "0",
                "durability_cost": 0,
                "action": {"type": "timeout", "duration_seconds": 30},
            }
        ],
        rng_stages=stages,
    )

    assert len(stages) == 1
    assert stages[0]["stage"] == "robbery_defense_gate"
    assert stages[0]["phase"] == "on_robbery_attempt"
    assert stages[0]["success"] is False


def test_legacy_effect_without_trigger_defaults_to_attempt_phase(monkeypatch) -> None:
    service = object.__new__(FishingService)
    service.user_repo = Mock()
    service.user_repo.db = Mock()
    monkeypatch.setattr("services.fishing_service.random.random", lambda: 0.05)
    attacker = SimpleNamespace(current_mass=Decimal("10"))
    victim = SimpleNamespace(id=2, current_mass=Decimal("100"))

    actions, absorbed = service._apply_robbery_defenses(
        attacker,
        victim,
        [
            {
                "type": "robbery_counter",
                "chance": "1",
                "durability_cost": 0,
                "action": {"type": "timeout", "duration_seconds": 30},
            }
        ],
    )

    assert absorbed is False
    assert actions == [
        {
            "type": "timeout",
            "duration_seconds": 30,
            "reason": "Robbery counter",
            "message": "",
        }
    ]
