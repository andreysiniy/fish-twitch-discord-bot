"""Tests for the human-facing item effect registry (spec §12-§33/§50-§51).

Covers the percent conversion helpers, the UI stat registry contract against
the backend ``STAT_REGISTRY``, the human-readable effect descriptions, the
typed modal conversions, and the triggered-effect payload builder.
"""

from decimal import Decimal


from app.domain.item_effect_registry import (
    TRIGGERED_EFFECT_FORMS,
    UI_STAT_DEFINITIONS,
    UNIT_PERCENT,
    UNIT_PERCENTAGE_POINTS,
    describe_effect,
)
from app.domain.percent_helpers import (
    percent_to_ratio,
    percentage_points_to_probability,
    probability_to_percentage_points,
    ratio_to_percent,
)
from app.interactions.items.effect_forms import (
    EffectNumbersModal,
    build_triggered_payload,
    human_value_to_backend,
    humanize_value,
)

from domain.item_schema import STAT_REGISTRY, StatKey


# --- percent helpers (spec §50) ------------------------------------------------


def test_percent_helpers_roundtrip() -> None:
    assert percent_to_ratio(Decimal("10")) == Decimal("0.10")
    assert ratio_to_percent(Decimal("0.10")) == Decimal("10")
    assert percent_to_ratio(Decimal("-50")) == Decimal("-0.50")
    assert ratio_to_percent(Decimal("1")) == Decimal("100")


def test_percentage_points_helpers_roundtrip() -> None:
    assert percentage_points_to_probability(Decimal("0.5")) == Decimal("0.005")
    assert probability_to_percentage_points(Decimal("0.005")) == Decimal("0.5")
    assert percentage_points_to_probability(Decimal("-100")) == Decimal("-1")


def test_percent_helpers_are_exact_decimal_math() -> None:
    assert percent_to_ratio(Decimal("33")) == Decimal("0.33")
    assert ratio_to_percent(percent_to_ratio(Decimal("33"))) == Decimal("33")


# --- registry contract with game_engine STAT_REGISTRY (spec §51) ---------------


def test_every_backend_stat_key_has_a_ui_definition() -> None:
    backend_keys = {member.value for member in StatKey}
    assert set(UI_STAT_DEFINITIONS) == backend_keys


def test_every_ui_definition_mirrors_backend_bounds_and_type() -> None:
    """Display bounds must match the backend ratio bounds converted to the
    human unit; the value type must match the backend definition."""
    for stat, ui in UI_STAT_DEFINITIONS.items():
        definition = STAT_REGISTRY[StatKey(stat)]
        if ui.unit in (UNIT_PERCENT, UNIT_PERCENTAGE_POINTS):
            display_min = Decimal(definition.minimum) * 100
            display_max = Decimal(definition.maximum) * 100
        else:
            display_min = Decimal(definition.minimum)
            display_max = Decimal(definition.maximum)
        assert Decimal(ui.display_min) == display_min, stat
        assert Decimal(ui.display_max) == display_max, stat
        assert ui.value_type == definition.value_type, stat


def test_ui_definitions_have_unique_labels() -> None:
    labels = [definition.label for definition in UI_STAT_DEFINITIONS.values()]
    assert len(labels) == len(set(labels))


# --- human-readable descriptions (spec §13) ------------------------------------


def test_describe_percent_stat_shows_human_percent() -> None:
    line = describe_effect({"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.10"})
    assert line == "Fish Luck: +10%"


def test_describe_negative_percent_stat() -> None:
    line = describe_effect({"type": "stat_add", "stat": "cooldown_change_ratio", "value": "-0.10"})
    assert line == "Fishing Cooldown: -10%"


def test_describe_percentage_points_stat() -> None:
    line = describe_effect({"type": "stat_add", "stat": "item_drop_chance_add", "value": "0.005"})
    assert line == "Item Drop Chance: +0.5 percentage points"


def test_describe_mass_and_triggered_effects() -> None:
    assert describe_effect({"type": "grant_mass", "mass": "5"}) == "Grant Mass: 5 kg"
    assert (
        describe_effect({"type": "apply_timeout", "duration_seconds": 3600})
        == "Apply Timeout: 1 hour"
    )


def test_describe_consume_effects_split_by_semantics() -> None:
    assert (
        describe_effect({"type": "consume_durability", "trigger": "after_cast", "amount": 2})
        == "Consume Durability: 2 After Any Cast"
    )
    assert (
        describe_effect({"type": "consume_charge", "trigger": "on_use", "amount": 1})
        == "Consume Charge: 1 When the Item Is Used"
    )
    assert "Durability" not in describe_effect(
        {"type": "consume_charge", "trigger": "on_use", "amount": 1}
    )
    assert "Charge" not in describe_effect(
        {"type": "consume_durability", "trigger": "after_cast", "amount": 1}
    )


def test_describe_never_leaks_raw_stat_keys() -> None:
    line = describe_effect({"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.10"})
    assert "fish_luck_change_ratio" not in line
    assert "stat_add" not in line
    assert "0.10" not in line


def test_describe_multiselect_uses_human_option_labels() -> None:
    line = describe_effect(
        {
            "type": "reroll_reward",
            "trigger": "after_reward_roll",
            "target_action_types": ["nothing", "robbery"],
            "max_rerolls": 2,
            "durability_cost": 0,
        }
    )
    assert "Empty Catch" in line
    assert "Robbery" in line
    assert "nothing" not in line
    assert "after_reward_roll" not in line


# --- human <-> backend conversions ---------------------------------------------


def test_human_value_percent_converts_to_ratio() -> None:
    definition = UI_STAT_DEFINITIONS["fish_luck_change_ratio"]
    backend, error = human_value_to_backend(definition, "10")
    assert error is None and Decimal(backend) == Decimal("0.10")
    backend, error = human_value_to_backend(definition, "-50")
    assert error is None and Decimal(backend) == Decimal("-0.50")


def test_human_value_percent_rejects_out_of_range() -> None:
    definition = UI_STAT_DEFINITIONS["fish_luck_change_ratio"]
    _, error = human_value_to_backend(definition, "150")
    assert error is not None and "at most" in error


def test_human_value_rejects_neutral_zero_effect() -> None:
    definition = UI_STAT_DEFINITIONS["fish_luck_change_ratio"]
    _, error = human_value_to_backend(definition, "0")
    assert error is not None and "must not be 0" in error


def test_human_value_percentage_points_converts() -> None:
    definition = UI_STAT_DEFINITIONS["item_drop_chance_add"]
    assert human_value_to_backend(definition, "0.5") == ("0.005", None)


def test_human_value_integer_rejects_fraction() -> None:
    definition = UI_STAT_DEFINITIONS["inventory_slots_add"]
    _, error = human_value_to_backend(definition, "1.5")
    assert error is not None and "whole number" in error


def test_humanize_value_shows_human_units() -> None:
    assert humanize_value(UI_STAT_DEFINITIONS["fish_luck_change_ratio"], "0.10") == "10"
    assert humanize_value(UI_STAT_DEFINITIONS["item_drop_chance_add"], "0.005") == "0.5"
    assert humanize_value(UI_STAT_DEFINITIONS["protected_mass_flat"], "100") == "100"


# --- triggered effect payloads (spec §22-§31) ----------------------------------


def test_build_reroll_reward_payload() -> None:
    payload = build_triggered_payload(
        "reroll_reward",
        {"target_action_types": ["nothing", "robbery"]},
        {"max_rerolls": 2, "durability_cost": 1},
    )
    assert payload["type"] == "reroll_reward"
    assert payload["trigger"] == "after_reward_roll"  # form default
    assert payload["target_action_types"] == ["nothing", "robbery"]
    assert payload["max_rerolls"] == 2


def test_build_block_action_converts_percent_chance() -> None:
    payload = build_triggered_payload(
        "block_action",
        {"trigger": "after_reward_roll", "target_action_types": ["nothing"]},
        {"chance": "0.50", "durability_cost": 0},
    )
    assert payload["chance"] == "0.50"


def test_build_robbery_counter_timeout_action() -> None:
    payload = build_triggered_payload(
        "robbery_counter",
        {"trigger": "on_robbery_attempt", "action_type": "timeout"},
        {"chance": "1", "duration_seconds": 60, "durability_cost": 1},
    )
    assert payload["action"] == {"type": "timeout", "duration_seconds": 60}
    assert "action_type" not in payload


def test_build_robbery_counter_mass_action() -> None:
    payload = build_triggered_payload(
        "robbery_counter",
        {"trigger": "on_robbery_success", "action_type": "add_mass"},
        {"chance": "1", "attacker_mass_delta": "-5", "durability_cost": 1},
    )
    assert payload["action"] == {"type": "add_mass", "mass": "-5"}
    assert "duration_seconds" not in payload


def test_build_grant_item_and_loot_table_roll() -> None:
    payload = build_triggered_payload("grant_item", {"item_id": "storm_rod"}, {"quantity": 2})
    assert payload == {"type": "grant_item", "item_id": "storm_rod", "quantity": 2}

    payload = build_triggered_payload("loot_table_roll", {"loot_table_id": "pool-1"}, {"rolls": 3})
    assert payload == {"type": "loot_table_roll", "loot_table_id": "pool-1", "rolls": 3}


# --- EffectNumbersModal prefill (spec §34) -------------------------------------


def test_effect_numbers_modal_prefills_from_current() -> None:
    form = TRIGGERED_EFFECT_FORMS["block_action"]
    modal = EffectNumbersModal(
        form,
        {"trigger": "after_reward_roll", "target_action_types": ["nothing"]},
        on_save=lambda payload: None,
        current={
            "type": "block_action",
            "trigger": "after_reward_roll",
            "target_action_types": ["nothing"],
            "chance": "0.5",
            "durability_cost": 2,
        },
    )
    assert modal.inputs["chance"].default == "50"
    assert modal.inputs["durability_cost"].default == "2"


def test_effect_numbers_modal_robbery_counter_asks_one_action_field() -> None:
    form = TRIGGERED_EFFECT_FORMS["robbery_counter"]
    modal = EffectNumbersModal(
        form,
        {"trigger": "on_robbery_attempt", "action_type": "timeout"},
        on_save=lambda payload: None,
        current={
            "type": "robbery_counter",
            "chance": "1",
            "action": {"type": "timeout", "duration_seconds": 300},
        },
    )
    assert "duration_seconds" in modal.inputs
    assert "attacker_mass_delta" not in modal.inputs
    assert modal.inputs["duration_seconds"].default == "300"


def test_effect_numbers_modal_uses_field_defaults_for_new_effects() -> None:
    form = TRIGGERED_EFFECT_FORMS["reroll_reward"]
    modal = EffectNumbersModal(
        form,
        {"target_action_types": ["nothing"]},
        on_save=lambda payload: None,
    )
    assert modal.inputs["max_rerolls"].default == "1"
    assert modal.inputs["durability_cost"].default == "0"
