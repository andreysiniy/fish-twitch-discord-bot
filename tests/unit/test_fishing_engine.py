from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from domain.schemas.fishing import FishingResult
from domain.logic import rng
from domain.logic import formulas
from services.fishing.engine import FishingEngine
from services.fishing.presenter import FishingPresenter
from services.fishing_service import FishingService


def make_user(**overrides):
    values = {
        "xp": 0,
        "level": 1,
        "username": "angler",
        "current_mass": 10.0,
        "base_inventory_slots": 20,
        "inventory": {},
        "items": [],
        "equipped_items": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_large_xp_reward_can_advance_multiple_levels() -> None:
    result = FishingEngine().calculate_result(
        user=make_user(),
        loot_pool=[{"type": "nothing", "weight": 1, "xp": 10_000}],
        item_pool=[],
        items_drop_rate=0,
        custom_params={"xp_base": 100, "xp_exponent": 1.5},
    )
    assert result.old_level == 1
    assert result.new_level > 2


def test_item_gate_success_without_eligible_candidates_is_recorded() -> None:
    result = FishingEngine().calculate_result(
        user=make_user(),
        loot_pool=[{"type": "nothing", "weight": 1, "xp": 0}],
        item_pool=[
            {
                "item_id": "sold_out",
                "item_definition_id": 7,
                "weight": 100,
                "remaining_stock": 0,
            }
        ],
        items_drop_rate=1,
        custom_params={},
    )

    assert result.item_drop is None
    assert result.item_drop_resolution is not None
    assert result.item_drop_resolution.status == "no_candidates"
    assert result.item_drop_resolution.gate_success is True
    assert result.item_drop_resolution.selection_success is False


def test_controlled_fixture_selects_requested_reward_type() -> None:
    result = FishingEngine().calculate_result(
        user=make_user(),
        loot_pool=[
            {"type": "nothing", "weight": 100, "xp": 0},
            {"type": "fish", "weight": 1, "fixed_mass": "5", "xp": 0},
        ],
        item_pool=[],
        items_drop_rate=0,
        custom_params={},
        controlled_fixture={"fixture_id": "fixture-1", "outcome": "fish"},
    )

    assert result.loot["type"] == "fish"
    assert result.rng_stages[-1]["stage"] == "controlled_fixture"


def test_controlled_fixture_controls_roulette_roll() -> None:
    result = FishingEngine().calculate_result(
        user=make_user(),
        loot_pool=[
            {
                "type": "russian_roulette",
                "weight": 1,
                "bullets": 1,
                "chambers": 1,
                "penalty": {"type": "add_mass", "mass": "-2"},
            }
        ],
        item_pool=[],
        items_drop_rate=0,
        custom_params={},
        controlled_fixture={
            "fixture_id": "roulette-fixture",
            "outcome": "russian_roulette",
            "rng": {"roulette_roll": 0.0},
        },
    )

    assert result.roulette_result is not None
    assert result.roulette_result.is_hit is True
    assert any(stage.get("stage") == "roulette_hit" for stage in result.rng_stages)


def test_v2_luck_reduction_scales_positive_mass_down() -> None:
    result = formulas.apply_fish_reward_modifiers(
        raw_delta=Decimal("10"),
        fish_luck_change_ratio=Decimal("-0.5"),
        positive_fish_reward_change_ratio=Decimal("0"),
        negative_fish_reward_change_ratio=Decimal("0"),
    )

    assert result == Decimal("5.00")
    assert isinstance(result, Decimal)


def test_v2_positive_ratios_reduce_negative_percentage_penalty() -> None:
    result = formulas.apply_fish_reward_modifiers(
        raw_delta=Decimal("100") * Decimal("-0.3"),
        fish_luck_change_ratio=Decimal("1"),
        positive_fish_reward_change_ratio=Decimal("0.25"),
        negative_fish_reward_change_ratio=Decimal("0"),
    )

    # -30 / (1 + 1) * (1 + 0) = -15.00
    assert result == Decimal("-15.00")


def test_v2_negative_ratio_reduces_negative_fixed_mass_penalty() -> None:
    result = formulas.apply_fish_reward_modifiers(
        raw_delta=Decimal("-30"),
        fish_luck_change_ratio=Decimal("1"),
        positive_fish_reward_change_ratio=Decimal("0"),
        negative_fish_reward_change_ratio=Decimal("-0.5"),
    )

    # -30 / (1 + 1) * (1 - 0.5) = -7.50
    assert result == Decimal("-7.50")


@pytest.mark.parametrize(
    "penalty",
    [
        {"type": "add_mass", "mass": "-30"},
        {"type": "add_percentage_mass", "percentage": "-0.3"},
    ],
)
def test_roulette_negative_mass_effects_are_reduced_by_positive_modifiers(
    monkeypatch, penalty
) -> None:
    monkeypatch.setattr(
        "services.fishing.engine.rng.is_russian_roulette_hit_traced",
        lambda **_: (True, Decimal("0")),
    )

    result = FishingEngine().calculate_russian_roulette(
        user=make_user(current_mass=Decimal("100")),
        catch={
            "type": "russian_roulette",
            "bullets": 1,
            "chambers": 6,
            "penalty": penalty,
        },
        luck_modifier=1.5,
        modifier_values={
            "positive_fish_reward_change_ratio": Decimal("0.25"),
            "negative_fish_reward_change_ratio": Decimal("0"),
        },
    )

    assert result.is_hit is True
    # Roulette never uses fish luck; positive ratios do not touch negative
    # penalties, so the -30 penalty stays -30.00.
    assert result.mass_delta == Decimal("-30.00")


def test_presenter_shows_reduced_effective_negative_percentage() -> None:
    mass_gained = formulas.apply_fish_reward_modifiers(
        raw_delta=Decimal("100") * Decimal("-0.3"),
        fish_luck_change_ratio=Decimal("1"),
        positive_fish_reward_change_ratio=Decimal("0.25"),
        negative_fish_reward_change_ratio=Decimal("0"),
    )
    user = make_user(
        channel=SimpleNamespace(config={}),
        current_mass=Decimal("100") + mass_gained,
        total_mass_stat=Decimal("200"),
    )
    result = FishingResult(
        loot={"type": "fish", "percentage": "-0.3", "message": "Penalty: {percentage}"},
        item_drop=None,
        username=user.username,
        xp_gained=0,
        mass_gained=mass_gained,
        is_level_up=False,
        old_level=1,
        new_level=1,
        fish_luck_factor_used=Decimal("1.5"),
        effective_percentage=Decimal("-0.08"),
    )

    response = FishingPresenter().build_response(user, result)

    assert response.chat_message.endswith("Penalty: -8%")


def test_percentage_mass_uses_decimal_arithmetic() -> None:
    result = FishingEngine()._default_strategy.calculate(
        {"percentage": "0.125"},
        luck_modifier=1.0,
        user_balance=Decimal("10.00"),
    )

    assert result == Decimal("1.25")
    assert isinstance(result, Decimal)


def test_presenter_shows_effective_percentage_after_all_mass_modifiers() -> None:
    mass_gained = formulas.apply_fish_reward_modifiers(
        raw_delta=Decimal("100.00") * Decimal("0.1"),
        fish_luck_change_ratio=Decimal("1"),
        positive_fish_reward_change_ratio=Decimal("0.25"),
        negative_fish_reward_change_ratio=Decimal("0"),
    )
    user = make_user(
        channel=SimpleNamespace(config={}),
        current_mass=Decimal("100.00") + mass_gained,
        total_mass_stat=Decimal("200.00") + mass_gained,
    )
    result = FishingResult(
        loot={"type": "fish", "percentage": "0.1", "message": "Gain: {percentage}"},
        item_drop=None,
        username=user.username,
        xp_gained=0,
        mass_gained=mass_gained,
        is_level_up=False,
        old_level=1,
        new_level=1,
        fish_luck_factor_used=Decimal("1.5"),
        effective_percentage=Decimal("0.375"),
    )

    response = FishingPresenter().build_response(user, result)

    assert mass_gained == Decimal("25.00")
    assert "Gain: +37.5%" in response.chat_message


def test_dupe_reward_creates_bounded_repeat_action() -> None:
    user = make_user(
        channel=SimpleNamespace(config={}),
        current_mass=Decimal("10.00"),
        total_mass_stat=Decimal("10.00"),
    )
    result = FishingResult(
        loot={
            "type": "dupe",
            "amount": 3,
            "delay": 2,
            "message": "{username} fishes {amount} more times.",
        },
        item_drop=None,
        username=user.username,
        xp_gained=0,
        mass_gained=Decimal("0"),
        is_level_up=False,
        old_level=1,
        new_level=1,
        fish_luck_factor_used=Decimal("1.0"),
    )

    response = FishingPresenter().build_response(user, result)

    assert response.actions[0].action_message.endswith("angler fishes 3 more times.")
    assert response.actions[1].type.value == "dupe"
    assert response.actions[1].amount == 3
    assert response.actions[1].delay == 2


def test_legacy_points_reward_is_not_modified_by_player_stats() -> None:
    rod = SimpleNamespace(
        slot_id=1,
        quantity=1,
        current_durability=100,
        meta={},
        item_id=1,
        definition=SimpleNamespace(
            item_id="bonus_rod",
            title="Bonus Rod",
            description=None,
            image_url=None,
            type="equipment",
            slot="rod",
            rarity="common",
            max_durability=100,
            stack_size=1,
            effects=[
                {
                    "type": "stat_add",
                    "stat": "points_flat_bonus",
                    "value": "25",
                }
            ],
        ),
    )
    result = FishingEngine().calculate_result(
        user=make_user(
            equipped_items=[SimpleNamespace(slot="rod", inventory_item=rod, inventory_item_id=1)],
            items=[rod],
        ),
        loot_pool=[{"type": "points", "weight": 1, "value": 100}],
        item_pool=[],
        items_drop_rate=0,
        custom_params={},
    )
    assert result.loot["value"] == 100


@pytest.mark.parametrize(
    ("fixed_mass", "modifiers", "mass_floor", "expected"),
    [
        ("10", {"positive_fish_reward_change_ratio": Decimal("0.20")}, "0", Decimal("12.00")),
        ("-30", {"negative_fish_reward_change_ratio": Decimal("-0.50")}, "0", Decimal("-15.00")),
        ("-30", {"negative_fish_reward_change_ratio": Decimal("0")}, "90", Decimal("-10.00")),
    ],
)
def test_typed_mass_modifiers_handle_sign_and_floor(
    fixed_mass: str,
    modifiers: dict,
    mass_floor: str,
    expected: Decimal,
) -> None:
    result = FishingEngine().calculate_result(
        user=make_user(current_mass=Decimal("100")),
        loot_pool=[{"type": "fish", "weight": 1, "fixed_mass": fixed_mass}],
        item_pool=[],
        items_drop_rate=0,
        custom_params={},
        modifier_values=modifiers,
        negative_mass_floor=Decimal(mass_floor),
    )
    assert result.mass_gained == expected


def test_typed_roulette_penalty_uses_negative_reduction(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.fishing.engine.rng.is_russian_roulette_hit_traced",
        lambda **_: (True, Decimal("0")),
    )
    result = FishingEngine().calculate_result(
        user=make_user(current_mass=Decimal("100")),
        loot_pool=[
            {
                "type": "russian_roulette",
                "weight": 1,
                "bullets": 1,
                "chambers": 1,
                "penalty": {"type": "add_mass", "mass": "-40"},
            }
        ],
        item_pool=[],
        items_drop_rate=0,
        custom_params={},
        modifier_values={"negative_fish_reward_change_ratio": Decimal("-0.25")},
    )
    assert result.mass_gained == Decimal("-30.00")


def test_robbery_uses_nested_custom_parameters(monkeypatch) -> None:
    monkeypatch.setattr("services.fishing.engine.random.random", lambda: 0.5)
    result = FishingEngine().calculate_mass_robbery(
        attacker=make_user(id=1),
        victim=make_user(id=2, username="victim", user_twitch_id="2", level=1),
        channel_config={
            "custom_params": {
                "rob_min_chance": 0,
                "rob_max_chance": 1,
                "rob_base_chance": 0,
                "rob_resist_divisor": 100,
                "rob_loss_divisor": 50,
            }
        },
        catch={"percentage": 0.5},
    )
    assert result.is_success is False
    assert result.chance_used == 0


def test_robbery_without_target_uses_dedicated_message() -> None:
    robbery_result = FishingEngine().calculate_mass_robbery(
        attacker=make_user(id=1),
        victim=None,
        channel_config={},
        catch={"percentage": "0.5"},
    )
    user = make_user(
        channel=SimpleNamespace(config={}),
        current_mass=Decimal("10.00"),
        total_mass_stat=Decimal("10.00"),
    )
    result = FishingResult(
        loot={"type": "robbery", "percentage": "0.5", "message": "Robbery started."},
        item_drop=None,
        username=user.username,
        xp_gained=0,
        mass_gained=Decimal("0"),
        is_level_up=False,
        old_level=1,
        new_level=1,
        fish_luck_factor_used=Decimal("1.0"),
        robbery_result=robbery_result,
    )

    response = FishingPresenter().build_response(user, result)

    assert robbery_result.victim_found is False
    assert "nobody was available" in response.actions[-1].action_message
    assert "tried to rob ," not in response.actions[-1].action_message


def test_robbery_mass_uses_decimal_arithmetic(monkeypatch) -> None:
    monkeypatch.setattr("services.fishing.engine.random.random", lambda: 0.0)
    result = FishingEngine().calculate_mass_robbery(
        attacker=make_user(id=1, current_mass=Decimal("2.00")),
        victim=make_user(
            id=2,
            username="victim",
            user_twitch_id="2",
            level=1,
            current_mass=Decimal("10.00"),
        ),
        channel_config={
            "custom_params": {
                "rob_min_chance": 1,
                "rob_max_chance": 1,
                "rob_base_chance": 1,
                "rob_resist_divisor": 100,
                "rob_loss_divisor": 50,
            }
        },
        catch={"percentage": "0.5"},
    )

    assert result.is_success is True
    assert result.amount_stolen == Decimal("5.00")
    assert result.victim_new_mass == Decimal("5.00")
    assert isinstance(result.amount_stolen, Decimal)


def test_robbery_uses_reward_specific_success_message() -> None:
    user = make_user(
        channel=SimpleNamespace(config={}),
        current_mass=Decimal("12.00"),
        total_mass_stat=Decimal("12.00"),
    )
    result = FishingResult(
        loot={
            "type": "robbery",
            "mass": "2",
            "success_message": "{attacker} took {attacker_gain} from {victim}.",
        },
        item_drop=None,
        username=user.username,
        xp_gained=0,
        mass_gained=Decimal("0"),
        is_level_up=False,
        old_level=1,
        new_level=1,
        fish_luck_factor_used=Decimal("1.0"),
        robbery_result={
            "is_success": True,
            "victim_found": True,
            "amount_stolen": "2",
            "victim_name": "victim",
            "victim_twitch_id": "2",
            "victim_new_mass": "8",
            "chance_used": 1.0,
        },
    )

    response = FishingPresenter().build_response(user, result)

    assert response.actions[1].action_message == "angler took +2kg from victim."


def test_fishing_service_persists_decimal_mass() -> None:
    user = make_user(
        id=1,
        user_twitch_id="1",
        channel_id=1,
        channel=SimpleNamespace(config={}, config_version=1),
        current_mass=Decimal("1.10"),
        total_mass_stat=Decimal("2.20"),
        total_fish_stat=0,
        current_location_id="default",
    )
    user_repo = Mock()
    user_repo.get_progress.return_value = user
    user_repo.apply_equipped_rod_durability_loss.return_value = None
    config_repo = Mock()
    config_repo.get_dual_pool.return_value = ([], [], 0)
    cooldown_repo = Mock()
    channel_repo = Mock()
    channel_repo.get_active_fishing_event.return_value = None
    service = FishingService(user_repo, config_repo, cooldown_repo, channel_repo)
    service.ledger.find_replay = Mock(return_value=None)
    service.modifier_service.resolve = Mock(
        return_value=SimpleNamespace(
            value=lambda _stat: Decimal("0"),
            values={},
            effects=(),
            mass_floor=lambda _scope: Decimal("0"),
            explain=lambda: {},
        )
    )
    service.engine.calculate_result = Mock(
        return_value=FishingResult(
            loot={"type": "fish"},
            item_drop=None,
            username=user.username,
            xp_gained=0,
            mass_gained=Decimal("0.205"),
            is_level_up=False,
            old_level=1,
            new_level=1,
            fish_luck_factor_used=Decimal("1.0"),
        )
    )
    from domain.schemas.fishing import FishResponse

    captured: dict = {}

    def _fake_presenter(_user, result):
        captured["result"] = result
        return FishResponse(chat_message="", xp_gained=0, actions=[])

    service.presenter.build_response = Mock(side_effect=_fake_presenter)

    service.process_cast("1", user.username, "channel", is_mod=True)

    assert captured["result"].mass_gained == Decimal("0.21")
    assert user.current_mass == Decimal("1.31")
    assert user.total_mass_stat == Decimal("2.41")
    assert isinstance(user.current_mass, Decimal)
    user_repo.save_progress.assert_called_once_with(user)


def test_empty_catch_stat_rerolls_once(monkeypatch) -> None:
    rolls = iter(
        [
            {"type": "nothing", "weight": 1, "xp": 0},
            {"type": "fish", "weight": 1, "fixed_mass": "2", "xp": 0},
        ]
    )
    monkeypatch.setattr(
        "services.fishing.engine.rng.roll_loot",
        lambda *_args, **_kwargs: next(rolls),
    )
    monkeypatch.setattr("services.fishing.engine.random.random", lambda: 0.25)

    result = FishingEngine().calculate_result(
        user=make_user(current_mass=Decimal("0")),
        loot_pool=[],
        item_pool=[],
        items_drop_rate=0,
        custom_params={},
        modifier_values={"empty_catch_reroll_chance_pct": Decimal("0.50")},
    )

    assert result.loot["type"] == "fish"
    assert result.mass_gained == Decimal("2.00")


def test_block_action_rerolls_matching_reward_and_tracks_durability(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.fishing.engine.rng.roll_loot_traced",
        lambda *_args, **_kwargs: rng.WeightedRollResult(
            selected={"type": "fish", "fixed_mass": "1"},
            selected_id="fish",
            roll=Decimal("0"),
            total_weight=Decimal("1"),
            selected_weight=Decimal("1"),
            selected_probability=Decimal("1"),
            candidate_count=1,
        ),
    )
    monkeypatch.setattr("services.fishing.engine.random.random", lambda: 0)
    effect = {
        "type": "block_action",
        "trigger": "after_reward_roll",
        "target_action_types": ["nothing"],
        "chance": "1",
        "durability_cost": 1,
    }

    result = FishingEngine._reroll_reward_effects(
        {"type": "nothing"},
        [],
        [effect],
    )

    assert result["type"] == "fish"
    assert effect["_trigger_count"] == 1


def test_counter_effect_uses_its_own_chance(monkeypatch) -> None:
    service = object.__new__(FishingService)
    service.user_repo = SimpleNamespace(db=Mock())
    monkeypatch.setattr("services.fishing_service.random.random", lambda: 0.10)
    attacker = SimpleNamespace(current_mass=Decimal("10"))
    victim = SimpleNamespace(id=2, current_mass=Decimal("10"))

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


def test_mod_pool_excludes_timeout_rewards() -> None:
    """Moderators must never draw the timeout reward from the fishing pool."""
    from services.fishing_service import _without_timeout_rewards

    pool = [
        {"type": "fish", "weight": 100},
        {"type": "timeout", "weight": 50},
        {"type": "gold", "weight": 5},
    ]
    filtered = _without_timeout_rewards(pool)
    assert all(r.get("type") != "timeout" for r in filtered)
    assert {r["type"] for r in filtered} == {"fish", "gold"}


def test_mod_pool_with_only_timeout_falls_back_to_nothing() -> None:
    from services.fishing_service import _without_timeout_rewards

    fallback = _without_timeout_rewards([{"type": "timeout", "weight": 100}])
    assert fallback == [
        {"type": "nothing", "weight": 100, "message": "No fish here..."}
    ]


def test_mod_pool_excludes_roulette_rewards_with_timeout_outcome() -> None:
    """A roulette reward with a timeout outcome is unsafe for moderators too."""
    from services.fishing_service import _without_timeout_rewards

    pool = [
        {
            "type": "russian_roulette",
            "weight": 20,
            "reward": {"type": "add_mass", "mass": 1},
            "penalty": {"type": "timeout", "duration": 60},
        },
        {
            "type": "russian_roulette",
            "weight": 30,
            "reward": {"type": "add_mass", "mass": 1},
            "penalty": {"type": "add_mass", "mass": -1},
        },
    ]

    filtered = _without_timeout_rewards(pool)

    assert filtered == [pool[1]]
