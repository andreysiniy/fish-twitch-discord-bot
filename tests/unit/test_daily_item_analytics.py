from decimal import Decimal
from types import SimpleNamespace

from infrastructure.repositories.fishing_cast_query_repo import FishingCastQueryRepository


def test_item_expected_probability_includes_gate_and_excludes_exhausted_entries() -> None:
    cast = SimpleNamespace(
        item_drop_probability=Decimal("0.4"),
        resolved_modifiers={"item_rarity_luck_pct": "0"},
    )
    entries = [
        {"item_definition_id": 1, "weight": 3, "rarity": "common", "remaining_stock": 0},
        {"item_definition_id": 2, "weight": 1, "rarity": "common", "remaining_stock": 5},
    ]

    probabilities = FishingCastQueryRepository._item_expected_probabilities(cast, entries)

    assert probabilities == {2: Decimal("0.4")}


def test_item_expected_probability_uses_rarity_luck_in_selection_denominator() -> None:
    cast = SimpleNamespace(
        item_drop_probability=Decimal("0.5"),
        resolved_modifiers={"item_rarity_luck_pct": "1"},
    )
    entries = [
        {"item_definition_id": 1, "weight": 1, "rarity": "common"},
        {"item_definition_id": 2, "weight": 1, "rarity": "rare"},
    ]

    probabilities = FishingCastQueryRepository._item_expected_probabilities(cast, entries)

    assert abs(probabilities[1] - Decimal(1) / Decimal(6)) < Decimal("1e-24")
    assert abs(probabilities[2] - Decimal(1) / Decimal(3)) < Decimal("1e-24")
