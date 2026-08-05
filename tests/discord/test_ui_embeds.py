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
                {"type": "stat_add", "stat": "loot_luck_pct", "value": "0.05"},
                {"type": "stat_add", "stat": "xp_gain_bonus_pct", "value": "0.1"},
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
            "effects": [{"type": "stat_add", "stat": "loot_luck_pct", "value": "0.05"}],
        }
    )
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Durability"] == "150"
    assert fields["Slot"] == "rod"
    assert fields["Type"] == "equipment"
    assert "Мощная удочка" == embed.description
    assert "stat_add" in fields["Effects (1)"]
    assert "schema 1" in embed.footer.text
