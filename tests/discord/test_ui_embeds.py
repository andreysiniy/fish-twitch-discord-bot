import discord

from app.presentation.embeds import (
    danger_embed,
    error_embed,
    info_embed,
    item_detail_embed,
    item_list_entry,
    preview_embed,
    success_embed,
    warning_embed,
)


def test_semantic_palette_colours() -> None:
    assert info_embed("x").color == discord.Color.blurple()
    assert preview_embed("x").color == discord.Color.orange()
    assert success_embed("x").color == discord.Color.green()
    assert warning_embed("x").color == discord.Color.gold()
    assert error_embed("x").color == discord.Color.red()
    assert danger_embed("x").color == discord.Color.dark_red()


def test_item_list_entry_is_compact() -> None:
    name, value = item_list_entry(
        {
            "title": "Storm Rod",
            "item_id": "storm_rod",
            "item_type": "equipment",
            "rarity": "epic",
            "stack_size": 1,
            "is_active": True,
            "version": 3,
            "effects": [
                {"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.05"},
                {"type": "stat_add", "stat": "xp_gain_change_ratio", "value": "0.1"},
            ],
        }
    )
    assert name == "Storm Rod"
    assert "2 effect(s)" in value
    # Full effects JSON must not spill into the list card.
    assert '"type"' not in value
    assert "Storm Rod" == "Storm Rod"


def test_item_detail_embed_renders_sections() -> None:
    embed = item_detail_embed(
        {
            "title": "Storm Rod",
            "item_id": "storm_rod",
            "description": "Мощная удочка",
            "item_type": "equipment",
            "rarity": "epic",
            "equipment_slot": "rod",
            "max_durability": 150,
            "break_policy": "unequip_broken",
            "is_active": True,
            "version": 3,
            "schema_version": 1,
            "effects": [{"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.05"}],
        }
    )
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Durability"] == "150"
    assert fields["Slot"] == "rod"
    assert fields["Type"] == "equipment"
    assert "Мощная удочка" == embed.description
    assert "stat_add" in fields["Effects (1)"]
    assert "schema 1" in embed.footer.text


def test_event_detail_embed_renders_human_percentages_and_factors() -> None:
    from app.presentation.embeds import event_detail_embed

    embed = event_detail_embed(
        {
            "id": 7,
            "event_title": "Storm",
            "status": "active",
            "is_active": True,
            "version": 3,
            "modifier_schema_version": 2,
            "override_loot_pool": "river",
            "modifiers": {
                "fish_luck_change_percent": "40",
                "positive_fish_reward_change_percent": "20",
                "negative_fish_reward_change_percent": "-50",
                "xp_gain_change_percent": "10",
                "cooldown_change_percent": "0",
            },
            "updated_at": "2026-08-06T00:00:00+00:00",
        }
    )
    text = "\n".join(field.value for field in embed.fields)
    assert "Fish Luck" in text
    assert "+40%" in text
    assert "×1.40" in text
    assert "Good Catch" in text
    assert "×1.20" in text
    assert "Bad Catch" in text
    assert "-50%" in text
    assert "×0.50" in text
    assert "Cooldown" not in text  # zero-valued modifiers are hidden
    assert "river" in text


def test_strong_event_values_detects_large_modifiers() -> None:
    from app.commands.events import _strong_event_values

    assert _strong_event_values(
        {
            "modifiers": {
                "fish_luck_change_percent": "50",
                "positive_fish_reward_change_percent": "10",
                "cooldown_change_percent": "-60",
            }
        }
    ) == ["Fish Luck: **+50%**", "Cooldown: **-60%**"]

    assert (
        _strong_event_values(
            {
                "modifiers": {
                    "fish_luck_change_percent": "49",
                    "positive_fish_reward_change_percent": "-49",
                }
            }
        )
        == []
    )


def test_location_detail_embed_is_human_readable() -> None:
    from app.presentation.embeds import location_detail_embed

    embed = location_detail_embed(
        {
            "location_id": "lake",
            "location_name": "Lake",
            "requirements": {"level": 3},
            "rewards": [{"type": "fish", "weight": 90}, {"type": "nothing", "weight": 10}],
            "item_drops": [{"item_id": "rod", "weight": 5}],
        }
    )
    text = "\n".join(field.value for field in embed.fields)
    assert "fish: 1" in text
    assert "nothing: 1" in text
    assert "`rod`" in text


def test_player_modifiers_embed_lists_rows_without_raw_json() -> None:
    from app.presentation.embeds import player_modifiers_embed

    embed = player_modifiers_embed(
        {
            "viewer": "srakjopa",
            "items": [
                {
                    "stat_key": "fish_luck_change_ratio",
                    "operation": "add",
                    "value": "0.1",
                    "source_key": "promo",
                }
            ],
        }
    )
    text = "\n".join(field.value for field in embed.fields)
    assert "fish_luck_change_ratio" in text
    assert "add" in text
    assert "promo" in text
    assert "{" not in text
