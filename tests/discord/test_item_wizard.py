import discord

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


def test_effects_preview_human_readable() -> None:
    text = effects_preview(
        [{"type": "stat_add", "stat": "positive_fish_reward_change_ratio", "value": "0.05"}]
    )
    assert "•" in text
    assert "Positive Mass Bonus" in text or "positive_mass_bonus_pct" in text
    assert effects_preview([]) == "No effects."


def test_item_preview_view_embed_renders() -> None:
    from app.interactions.item_wizard import ItemPreviewView

    view = ItemPreviewView(
        1,
        {
            "item_id": "storm_rod",
            "title": "Storm Rod",
            "item_type": "equipment",
            "equipment_slot": "rod",
            "rarity": "epic",
            "description": "мощная",
            "effects": [{"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.05"}],
        },
        lambda *_: None,
    )
    embed = view.embed()
    assert embed.color == discord.Color.blurple()
    assert "Effects" in {field.name for field in embed.fields}
