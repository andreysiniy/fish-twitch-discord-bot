from decimal import Decimal

from domain.logic import rng
from domain.logic.rng import WeightedRollResult, roll_loot, roll_loot_traced


def test_traced_roll_selects_by_weight_and_reports_probability() -> None:
    entries = [
        {"id": "a", "weight": 1},
        {"id": "b", "weight": 3},
        {"id": "c", "weight": 6},
    ]
    # raw_roll = 0.0 -> scaled = 0 -> always first entry
    result = roll_loot_traced(entries, random_source=lambda: 0.0)
    assert isinstance(result, WeightedRollResult)
    assert result.selected == {"id": "a", "weight": 1}
    assert result.selected_id == "a"
    assert result.roll == Decimal("0.000000")
    assert result.total_weight == Decimal("10")
    assert result.selected_weight == Decimal("1")
    assert result.selected_probability == Decimal("0.100000000000")
    assert result.candidate_count == 3


def test_traced_roll_boundary_selects_last_entry() -> None:
    entries = [
        {"id": "a", "weight": 1},
        {"id": "b", "weight": 3},
        {"id": "c", "weight": 6},
    ]
    result = roll_loot_traced(entries, random_source=lambda: 0.999999999)
    assert result.selected_id == "c"
    assert result.selected_probability == Decimal("0.600000000000")


def test_traced_roll_empty_pool() -> None:
    result = roll_loot_traced([], random_source=lambda: 0.5)
    assert result.selected is None
    assert result.candidate_count == 0
    assert result.roll == Decimal("0")


def test_legacy_wrapper_matches_traced_for_same_random_value() -> None:
    entries = [
        {"id": "a", "weight": 1, "rarity": "common"},
        {"id": "b", "weight": 3, "rarity": "rare"},
        {"id": "c", "weight": 6, "rarity": "legendary"},
    ]
    luck = 1.0
    traced = roll_loot_traced(
        entries,
        weight_transform=lambda entry: rng._rarity_luck_weight(entry, luck),
        random_source=lambda: 0.25,
    )
    wrapped = roll_loot(entries, luck_modifier=luck, random_source=lambda: 0.25)
    # same deterministic draw selects the same entry
    assert traced.selected == wrapped


def test_traced_roll_weight_transform_overrides() -> None:
    entries = [
        {"id": "a", "weight": 100},
        {"id": "b", "weight": 1},
    ]
    # Transform reweights so 'b' dominates; raw_roll 0.9999 must pick b.
    result = roll_loot_traced(
        entries,
        weight_transform=lambda _entry: Decimal("1000") if _entry["id"] == "b" else Decimal("1"),
        random_source=lambda: 0.9999,
    )
    assert result.selected_id == "b"


def test_roll_probability_never_exceeds_total() -> None:
    entries = [{"id": str(i), "weight": 1} for i in range(50)]
    for raw in (0.0, 0.25, 0.5, 0.75, 0.999):
        result = roll_loot_traced(entries, random_source=lambda raw=raw: raw)
        assert result.selected_probability == Decimal("0.020000000000")
        assert 0 <= result.roll <= result.total_weight
