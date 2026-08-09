from types import SimpleNamespace

from app.presentation.embeds import (
    item_drop_list_entry,
    item_drop_preview_embed,
)


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


_PREVIEW = {
    "items_drop_rate": 0.1,
    "proposed_weight": 25,
    "total_weight": 50,
    "selection_weight_share": 0.5,
    "drop_probability": 0.05,
    "expected_casts_to_drop": 20.0,
    "p50": 14,
    "p90": 45,
    "expected_active_time_minutes": {"5": 100.0, "7.5": 150.0, "10": 200.0},
}

_PAYLOAD = {
    "item_id": "leviathan_rod",
    "weight": 25,
    "xp_gain": 50,
    "quantity": None,
    "message": "You caught {name}!",
}


def _field_texts(embed) -> dict:
    return {field.name: field.value for field in embed.fields}


def test_item_drop_preview_embed_shows_derived_stats() -> None:
    embed = item_drop_preview_embed(
        action="Add", location_id="abyss", preview=_PREVIEW, payload=_PAYLOAD
    )
    assert embed.title == "Add item drop: leviathan_rod"
    fields = _field_texts(embed)
    assert "50.00% of the pool" in fields["Pool share"]
    assert "location drop rate 10.00%" in fields["Pool share"]
    assert "5.00% per cast (≈20.0 casts)" in fields["Chance per cast"]
    assert "5 min: 1.7 h" in fields["Expected active time"]
    assert "7.5 min: 2.5 h" in fields["Expected active time"]
    assert "10 min: 3.3 h" in fields["Expected active time"]
    assert "p50 14 casts · p90 45 casts" in fields["Median / 90th percentile"]
    assert "Change vs current" not in fields


def test_item_drop_preview_embed_edit_shows_diff() -> None:
    current = {"weight": 10, "xp_gain": 0, "quantity": 5, "message": "old"}
    payload = {**_PAYLOAD, "weight": 25, "quantity": None}
    embed = item_drop_preview_embed(
        action="Edit",
        location_id="abyss",
        preview=_PREVIEW,
        payload=payload,
        current=current,
    )
    fields = _field_texts(embed)
    changes = fields["Change vs current"]
    assert "Weight: 10 → 25" in changes
    assert "XP: 0 → 50" in changes
    assert "Stock: 5 → unlimited" in changes
    assert "Message: old → You caught {name}!" in changes


def test_item_drop_preview_embed_truncates_message() -> None:
    payload = {**_PAYLOAD, "message": "x" * 300}
    embed = item_drop_preview_embed(
        action="Add", location_id="abyss", preview=_PREVIEW, payload=payload
    )
    assert len(embed.fields[-1].value.split("Message: ")[1]) == 200


def test_item_drop_preview_embed_without_derived_stats() -> None:
    preview = {
        "items_drop_rate": 0.1,
        "proposed_weight": 25,
        "total_weight": 0,
        "selection_weight_share": 0.0,
        "drop_probability": 0.0,
        "expected_casts_to_drop": None,
        "p50": None,
        "p90": None,
        "expected_active_time_minutes": None,
    }
    embed = item_drop_preview_embed(
        action="Add", location_id="abyss", preview=preview, payload=_PAYLOAD
    )
    fields = _field_texts(embed)
    assert "0.00% per cast" in fields["Chance per cast"]
    assert "Expected active time" not in fields
    assert "Median / 90th percentile" not in fields


def test_item_drop_list_entry_hides_database_id() -> None:
    entry = {
        "id": 12345,
        "title": "Storm Rod",
        "item_id": "storm_rod",
        "weight": 25,
        "xp_gain": 5,
        "quantity": 3,
        "message": "m",
        "version": 1,
        "drop_probability": 0.5,
        "expected_casts_to_drop": 2.0,
    }
    title, details = item_drop_list_entry(entry)
    assert title == "Storm Rod"
    assert "12345" not in details
    assert "ID: `storm_rod`" in details
    assert "Weight: 25" in details
    assert "Stock: 3" in details
    assert "XP: 5" in details
