from types import SimpleNamespace

import pytest

from services.fishing.engine import EventLootStrategy, FishingEngine


def make_user(**overrides):
    values = {
        "xp": 0,
        "level": 1,
        "username": "angler",
        "current_mass": 10.0,
        "inventory": {},
        "items": [],
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


def test_event_luck_multiplier_can_reduce_positive_mass() -> None:
    strategy = EventLootStrategy({"luck_mult": 0.5})
    assert strategy.calculate({"fixed_mass": 10}, luck_modifier=1.0, user_balance=0) == 5


def test_points_bonus_is_applied_to_points_reward() -> None:
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
            type="rod",
            slot="rod",
            rarity="common",
            durability=100,
            stack_size=1,
            base_stats={"points_bonus": 25},
        ),
    )
    result = FishingEngine().calculate_result(
        user=make_user(inventory={"equipped_rod_slot": 1}, items=[rod]),
        loot_pool=[{"type": "points", "weight": 1, "value": 100}],
        item_pool=[],
        items_drop_rate=0,
        custom_params={},
    )
    assert result.loot["value"] == 125


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
