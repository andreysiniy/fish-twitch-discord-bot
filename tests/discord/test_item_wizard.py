from app.interactions.item_wizard import (
    build_item_payload,
    effects_preview,
)


def test_normalize_equipment_forces_slot_and_single_stack() -> None:
    payload = build_item_payload(
        {
            "item_id": "Storm_Rod",
            "title": "Storm Rod",
            "item_type": "equipment",
            "equipment_slot": "rod",
            "stack_size": 5,
            "rarity": "epic",
            "break_policy": "unequip_broken",
            "max_durability": 150,
        }
    )
    assert payload["item_id"] == "storm_rod"
    assert payload["equipment_slot"] == "rod"
    assert payload["stack_size"] == 1
    assert payload["break_policy"] == "unequip_broken"
    assert payload["max_durability"] == 150


def test_normalize_non_equipment_clears_slot_and_indestructible_durability() -> None:
    payload = build_item_payload(
        {
            "item_id": "ore",
            "title": "Ore",
            "item_type": "material",
            "equipment_slot": "rod",
            "stack_size": 10,
            "rarity": "common",
            "break_policy": "indestructible",
            "max_durability": 50,
        }
    )
    assert payload["equipment_slot"] is None
    assert payload["max_durability"] is None
    assert payload["stack_size"] == 10


def test_build_payload_carries_version_fields() -> None:
    payload = build_item_payload(
        {"item_id": "x", "title": "X", "item_type": "collectible", "rarity": "rare"},
        expected_version=3,
        schema_version=2,
    )
    assert payload["expected_version"] == 3
    assert payload["schema_version"] == 2


def test_payload_builder_preserves_schema_version_from_draft() -> None:
    """Spec test 15: the shared builder must not reset schema_version."""
    payload = build_item_payload(
        {
            "item_id": "x",
            "title": "X",
            "item_type": "material",
            "rarity": "rare",
            "schema_version": 3,
        }
    )
    assert payload["schema_version"] == 3


def test_payload_builder_preserves_image_url_from_draft() -> None:
    """Spec test 16: the shared builder must not drop image_url."""
    payload = build_item_payload(
        {
            "item_id": "x",
            "title": "X",
            "item_type": "material",
            "rarity": "rare",
            "image_url": "https://example.com/icon.png",
        }
    )
    assert payload["image_url"] == "https://example.com/icon.png"


def test_payload_builder_preserves_value_from_draft() -> None:
    """Spec test 17: the shared builder must not drop value."""
    payload = build_item_payload(
        {
            "item_id": "x",
            "title": "X",
            "item_type": "material",
            "rarity": "rare",
            "value": "150.5",
        }
    )
    assert payload["value"] == "150.5"


def test_payload_builder_carries_expected_version_from_draft() -> None:
    """Spec test 18: edit payloads keep expected_version for optimistic locking."""
    payload = build_item_payload(
        {
            "item_id": "x",
            "title": "X",
            "item_type": "material",
            "rarity": "rare",
            "expected_version": 7,
            "schema_version": 3,
        }
    )
    assert payload["expected_version"] == 7
    assert payload["schema_version"] == 3


def test_effects_preview_human_readable() -> None:
    text = effects_preview(
        [{"type": "stat_add", "stat": "positive_fish_reward_change_ratio", "value": "0.05"}]
    )
    assert "•" in text
    assert "Positive Fish Reward" in text or "positive_fish_reward_change_ratio" in text
    assert effects_preview([]) == "No effects."
