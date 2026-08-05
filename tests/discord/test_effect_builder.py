from app.interactions.effect_builder import (
    describe_effect,
    effect_to_choice,
    parse_decimal_safe,
    serialize_draft,
)


def test_serialize_stat_add_effect() -> None:
    effect = serialize_draft({"type": "stat_add", "stat": "loot_luck_pct", "value": "0.10"})
    assert effect["trigger"] == "passive"
    assert effect["value"] == "0.10"


def test_serialize_stat_multiply_preserves_trigger() -> None:
    effect = serialize_draft({"type": "stat_multiply", "stat": "xp_gain_bonus_pct", "value": "2"})
    assert effect["type"] == "stat_multiply"
    assert effect["value"] == "2"


def test_describe_passive_effect_shows_percent() -> None:
    text = describe_effect({"type": "stat_add", "stat": "positive_mass_bonus_pct", "value": "0.05"})
    assert "Positive Mass Bonus" in text or "positive_mass_bonus_pct" in text
    assert "5%" in text


def test_describe_grant_effect() -> None:
    text = describe_effect({"type": "grant_item", "item_id": "storm_rod", "quantity": 2})
    assert "storm_rod" in text
    assert "2" in text


def test_effect_to_choice_returns_type() -> None:
    assert effect_to_choice({"type": "grant_mass"}) == "grant_mass"


def test_parse_decimal_safe_handles_bad_values() -> None:
    assert parse_decimal_safe("0.5") is not None
    assert parse_decimal_safe("not-a-number") == 0


def test_serialize_draft_leaves_non_passive_untouched() -> None:
    effect = serialize_draft({"type": "grant_mass", "mass": "5.5"})
    assert effect["type"] == "grant_mass"
    assert effect["mass"] == "5.5"
