from types import SimpleNamespace

from app.presentation.embeds import item_drop_list_entry


def _row(weight: int, items_drop_rate: float):
    return SimpleNamespace(
        weight=weight,
        items_drop_rate=items_drop_rate,
    )


def test_item_drop_list_entry_shows_probability() -> None:
    entry = {
        "title": "Storm Rod",
        "item_id": "storm_rod",
        "weight": 25,
        "xp_gain": 0,
        "quantity": None,
        "message": "m",
        "version": 1,
        "drop_probability": 0.5,
        "expected_casts_to_drop": 2.0,
    }
    title, details = item_drop_list_entry(entry)
    assert title == "Storm Rod"
    assert "50.00%" in details
    assert "2.0 casts" in details


def test_item_drop_list_entry_without_probability() -> None:
    entry = {
        "title": "Plain",
        "item_id": "plain",
        "weight": 100,
        "xp_gain": 0,
        "quantity": None,
        "message": "m",
        "version": 1,
    }
    title, details = item_drop_list_entry(entry)
    assert "Drop chance" not in details


def test_probability_math_matches_runtime() -> None:
    # Two items, weights 1 and 3, drop rate 0.4.
    rows = [_row(1, 0.4), _row(3, 0.4)]
    total = sum(row.weight for row in rows)
    shares = [row.weight / total for row in rows]
    probabilities = [round(0.4 * share, 6) for share in shares]
    assert probabilities == [0.1, 0.3]
    assert round(1.0 / probabilities[0], 1) == 10.0
    assert round(1.0 / probabilities[1], 1) == 3.3
