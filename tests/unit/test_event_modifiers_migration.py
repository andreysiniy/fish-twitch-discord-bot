from decimal import Decimal

import importlib

import pytest


@pytest.fixture(scope="module")
def migration_module():
    return importlib.import_module(
        "migrations.versions.20260802_0011_event_modifiers_v2"
    )


def test_spec_example_conversion(migration_module) -> None:
    convert = migration_module._convert_legacy_to_v2
    converted = convert(
        {"luck_mult": "1.4", "xp_mult": "2", "cd_reduction": "0.5", "bonus_mass": "5"}
    )
    assert converted["schema_version"] == 2
    assert converted["fish_luck_change_percent"] == "40.00"
    assert converted["positive_fish_reward_change_percent"] == "500.00"
    assert converted["negative_fish_reward_change_percent"] == "-83.33"
    assert converted["xp_gain_change_percent"] == "100.00"
    assert converted["cooldown_change_percent"] == "-50.00"


def test_default_legacy_is_neutral_without_zeros(migration_module) -> None:
    convert = migration_module._convert_legacy_to_v2
    converted = convert({})
    assert converted["schema_version"] == 2
    assert converted.get("positive_fish_reward_change_percent") in (None, "0")


def test_unsafe_event_requires_review(migration_module) -> None:
    requires_review = migration_module._requires_review
    safe = {"positive_fish_reward_change_percent": "100"}
    unsafe = {"positive_fish_reward_change_percent": "500"}
    assert requires_review(safe) is False
    assert requires_review(unsafe) is True


def test_lenient_event_parse_clamps_legacy_out_of_range_values() -> None:
    """Legacy events with +500% reward must not crash the resolver at runtime."""
    from services.player_modifier_service import parse_event_modifiers_lenient

    payload = parse_event_modifiers_lenient(
        42,
        {
            "schema_version": 2,
            "positive_fish_reward_change_percent": "500.00",
            "fish_luck_change_percent": "40.00",
            "cooldown_change_percent": "-50.00",
        },
    ).to_resolver_payload()
    assert payload["positive_fish_reward_change_ratio"] == Decimal("2.00")  # clamped to 200%
    assert payload["fish_luck_change_ratio"] == Decimal("0.40")
    assert payload["cooldown_change_ratio"] == Decimal("-0.50")
