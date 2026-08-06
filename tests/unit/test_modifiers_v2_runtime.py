"""Tests for the modifiers v2 runtime: formula, isolation, sign conventions.

Covers spec sections 7-10, 20.1-20.3 of
``fishing_event_modifiers_v2_technical_spec.md``.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from domain.item_schema import (
    StatKey,
    migrate_stat_key,
)
from domain.logic.formulas import apply_fish_reward_modifiers
from services.fishing.engine import FishingEngine


# ---------------------------------------------------------------- formula ---


def _pct(value: str) -> Decimal:
    return Decimal(value) / Decimal("100")


def test_neutral_modifiers_do_not_change_result() -> None:
    assert apply_fish_reward_modifiers(
        Decimal("20"), Decimal("0"), Decimal("0"), Decimal("0")
    ) == Decimal("20.00")
    assert apply_fish_reward_modifiers(
        Decimal("-20"), Decimal("0"), Decimal("0"), Decimal("0")
    ) == Decimal("-20.00")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (Decimal("8"), Decimal("11.76")),
        (Decimal("20"), Decimal("29.40")),
    ],
)
def test_spec_positive_control_examples(raw: Decimal, expected: Decimal) -> None:
    # +8% and +20% with luck +40% and positive +5% (spec 9.1, 9.2).
    result = apply_fish_reward_modifiers(
        raw,
        fish_luck_change_ratio=_pct("40"),
        positive_fish_reward_change_ratio=_pct("5"),
        negative_fish_reward_change_ratio=_pct("-5"),
    )
    assert result == expected


def test_spec_negative_control_example() -> None:
    # -20% with luck +40% and negative -5% -> -13.57% (spec 9.3).
    result = apply_fish_reward_modifiers(
        Decimal("-20"),
        fish_luck_change_ratio=_pct("40"),
        positive_fish_reward_change_ratio=_pct("5"),
        negative_fish_reward_change_ratio=_pct("-5"),
    )
    assert result == Decimal("-13.57")


def test_fixed_mass_control_examples() -> None:
    assert apply_fish_reward_modifiers(
        Decimal("10"),
        _pct("40"),
        _pct("5"),
        _pct("-5"),
    ) == Decimal("14.70")
    assert apply_fish_reward_modifiers(
        Decimal("-10"),
        _pct("40"),
        _pct("5"),
        _pct("-5"),
    ) == Decimal("-6.79")


def test_negative_luck_hardens_negative_penalty() -> None:
    result = apply_fish_reward_modifiers(
        Decimal("-20"),
        fish_luck_change_ratio=_pct("-40"),
        positive_fish_reward_change_ratio=Decimal("0"),
        negative_fish_reward_change_ratio=Decimal("0"),
    )
    assert result == Decimal("-33.33")


def test_zero_positive_factor_zeroes_positive_reward() -> None:
    result = apply_fish_reward_modifiers(
        Decimal("50"),
        Decimal("0"),
        positive_fish_reward_change_ratio=Decimal("-1"),
        negative_fish_reward_change_ratio=Decimal("0"),
    )
    assert result == Decimal("0.00")


def test_luck_factor_floor_is_one_percent() -> None:
    result = apply_fish_reward_modifiers(
        Decimal("100"),
        fish_luck_change_ratio=Decimal("-10"),
        positive_fish_reward_change_ratio=Decimal("0"),
        negative_fish_reward_change_ratio=Decimal("0"),
    )
    assert result == Decimal("1.00")


def test_negative_reward_respects_mass_floor() -> None:
    # Floor 90 on balance 100 means the balance cannot drop below 90,
    # so a -50 penalty is clamped to -10.
    result = apply_fish_reward_modifiers(
        Decimal("-50"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        mass_floor=Decimal("90"),
        user_balance=Decimal("100"),
    )
    assert result == Decimal("-10.00")
    # No clamp when the floor is already satisfied.
    assert apply_fish_reward_modifiers(
        Decimal("-50"),
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
        mass_floor=Decimal("30"),
        user_balance=Decimal("100"),
    ) == Decimal("-50.00")


def test_rounding_happens_once() -> None:
    result = apply_fish_reward_modifiers(
        Decimal("339.94") * _pct("8"),
        _pct("40"),
        _pct("5"),
        _pct("-5"),
    )
    assert result == Decimal("39.98")


# ------------------------------------------------------------- engine path ---


def _user(**overrides):
    values = {
        "xp": 0,
        "level": 1,
        "username": "angler",
        "current_mass": Decimal("339.94"),
        "base_inventory_slots": 20,
        "total_fish_stat": 0,
        "total_mass_stat": Decimal("339.94"),
        "user_twitch_id": "1",
        "channel_id": 1,
        "id": 1,
        "equipped_items": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_engine_applies_v2_control_example(monkeypatch) -> None:
    monkeypatch.setattr("services.fishing.engine.random.random", lambda: 0.0)
    result = FishingEngine().calculate_result(
        user=_user(),
        loot_pool=[{"type": "fish", "weight": 1, "percentage": "0.20"}],
        item_pool=[],
        items_drop_rate=0,
        custom_params={},
        modifier_values={
            "fish_luck_change_ratio": Decimal("0.40"),
            "positive_fish_reward_change_ratio": Decimal("0.05"),
            "negative_fish_reward_change_ratio": Decimal("-0.05"),
            "xp_gain_change_ratio": Decimal("0"),
        },
    )
    # 339.94 * 0.20 * 1.40 * 1.05 = 99.94
    assert result.mass_gained == Decimal("99.94")
    # effective_percentage is a ratio: 0.20 * 1.40 * 1.05 = 0.294
    assert result.effective_percentage == Decimal("0.294")
    assert result.fish_luck_factor_used == Decimal("1.40")


def test_fish_luck_does_not_change_reward_selection(monkeypatch) -> None:
    from domain.logic import rng as rng_module

    pool = [
        {"type": "nothing", "weight": 50, "id": "nothing"},
        {"type": "points", "weight": 50, "id": "points"},
    ]
    selected: list[str] = []

    original_traced = rng_module.roll_loot_traced
    original_roll = rng_module.roll_loot

    def fixed_traced(loot_table, weight_transform=None, **kwargs):
        return original_traced(
            loot_table,
            weight_transform=weight_transform,
            random_source=lambda: 0.25,
        )

    def fixed_roll(loot_table, **kwargs):
        return original_roll(loot_table, random_source=lambda: 0.25)

    monkeypatch.setattr(rng_module, "roll_loot_traced", fixed_traced)
    monkeypatch.setattr(rng_module, "roll_loot", fixed_roll)

    def run(luck_ratio: str) -> str:
        result = FishingEngine().calculate_result(
            user=_user(),
            loot_pool=pool,
            item_pool=[],
            items_drop_rate=0,
            custom_params={},
            modifier_values={
                "fish_luck_change_ratio": Decimal(luck_ratio),
                "positive_fish_reward_change_ratio": Decimal("0"),
                "negative_fish_reward_change_ratio": Decimal("0"),
            },
        )
        return str(result.loot.get("id"))

    selected.append(run("0"))
    selected.append(run("0.80"))
    assert selected[0] == selected[1]


def test_fish_luck_does_not_change_item_drop_gate(monkeypatch) -> None:
    calls: list[Decimal] = []

    def fake_random() -> float:
        calls.append(Decimal("0.5"))
        return 0.5

    monkeypatch.setattr("services.fishing.engine.random.random", fake_random)
    outcomes = []
    for luck in ("0", "0.90"):
        result = FishingEngine().calculate_result(
            user=_user(),
            loot_pool=[{"type": "fish", "weight": 1, "fixed_mass": "1"}],
            item_pool=[{"item_id": "x", "weight": 1, "rarity": "common"}],
            items_drop_rate=Decimal("0.30"),
            custom_params={},
            modifier_values={
                "fish_luck_change_ratio": Decimal(luck),
                "positive_fish_reward_change_ratio": Decimal("0"),
                "negative_fish_reward_change_ratio": Decimal("0"),
            },
        )
        outcomes.append(result.item_drop)
    # The item gate roll is identical for both luck values (0.5 > 0.30), so
    # the item-drop outcome must be identical too.
    assert calls == [Decimal("0.5"), Decimal("0.5")]
    assert outcomes[0] == outcomes[1] is None


def test_item_drop_chance_add_only_affects_gate(monkeypatch) -> None:
    def run(add: Decimal) -> bool:
        monkeypatch.setattr("services.fishing.engine.random.random", lambda: 0.10)
        result = FishingEngine().calculate_result(
            user=_user(),
            loot_pool=[{"type": "fish", "weight": 1, "fixed_mass": "1"}],
            item_pool=[{"item_id": "x", "weight": 1, "rarity": "common"}],
            items_drop_rate=Decimal("0.05"),
            custom_params={},
            modifier_values={
                "fish_luck_change_ratio": Decimal("0"),
                "positive_fish_reward_change_ratio": Decimal("0"),
                "negative_fish_reward_change_ratio": Decimal("0"),
                "item_drop_chance_add": add,
            },
        )
        return result.item_drop is not None

    assert run(Decimal("0")) is False
    assert run(Decimal("0.20")) is True


# ------------------------------------------------------- legacy translation ---


def test_migrate_stat_key_renames_and_flips_signs() -> None:
    stat, value = migrate_stat_key("loot_luck_pct", Decimal("0.40"))
    assert stat == StatKey.FISH_LUCK_CHANGE_RATIO
    assert value == Decimal("0.40")

    stat, value = migrate_stat_key("negative_mass_reduction_pct", Decimal("0.20"))
    assert stat == StatKey.NEGATIVE_FISH_REWARD_CHANGE_RATIO
    assert value == Decimal("-0.20")

    stat, value = migrate_stat_key("cooldown_reduction_pct", Decimal("0.10"))
    assert stat == StatKey.COOLDOWN_CHANGE_RATIO
    assert value == Decimal("-0.10")


def test_migrate_stat_key_new_keys_pass_through() -> None:
    stat, value = migrate_stat_key("fish_luck_change_ratio", Decimal("0.40"))
    assert stat == StatKey.FISH_LUCK_CHANGE_RATIO
    assert value == Decimal("0.40")


def test_migrate_stat_key_unknown_key_raises() -> None:
    with pytest.raises(ValueError):
        migrate_stat_key("totally_unknown_stat", Decimal("1"))
