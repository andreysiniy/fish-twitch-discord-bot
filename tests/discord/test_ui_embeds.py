import discord
import pytest
from app.presentation.embeds import (
    config_embed,
    danger_embed,
    error_embed,
    info_embed,
    item_detail_embed,
    item_list_entry,
    preview_embed,
    rarity_color,
    reward_detail_embed,
    reward_list_entry,
    success_embed,
    warning_embed,
)


def test_config_embed_groups_and_formats_values() -> None:
    embed = config_embed(
        {
            "version": 4,
            "effective": {
                "xp_base": 100,
                "xp_exponent": "1.5",
                "rob_min_chance": "0.05",
                "rob_base_chance": "0.8",
                "rob_max_chance": "0.95",
                "fishing_cooldown": 600,
                "subs_fishing_cooldown": 300,
            },
        }
    )

    fields = {field.name: field.value for field in embed.fields}
    assert embed.title == "Configuration"
    assert embed.description == "Version: `v4`"
    assert fields["XP"] == "**Base XP**\n`100 XP`\n\n**XP exponent**\n`1.5x`"
    assert "Minimum chance**\n`5%`" in fields["Robbery"]
    assert "Base chance**\n`80%`" in fields["Robbery"]
    assert "Maximum chance**\n`95%`" in fields["Robbery"]
    assert "Regular fishing**\n`10 minutes`" in fields["Fishing cooldowns"]
    assert "Subscriber fishing**\n`5 minutes`" in fields["Fishing cooldowns"]
    assert "rob_min_chance" not in "\n".join(fields.values())


def test_config_embed_filters_to_readable_section() -> None:
    embed = config_embed(
        {"version": 4, "effective": {"rob_min_chance": "0.05", "rob_max_chance": "0.95"}},
        "robbery",
    )

    assert embed.title == "Configuration: Robbery"
    assert [field.name for field in embed.fields] == ["Robbery"]
    assert "5%" in embed.fields[0].value


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
    assert "Fish Luck: +5%" in fields["Effects (1)"]
    assert "stat_add" not in fields["Effects (1)"]
    assert embed.color == discord.Color(0x9B59B6)
    assert "schema 1" in embed.footer.text


@pytest.mark.parametrize(
    ("rarity", "expected"),
    [
        ("common", 0x95A5A6),
        ("rare", 0x3498DB),
        ("epic", 0x9B59B6),
        ("legendary", 0xF1C40F),
    ],
)
def test_rarity_color_palette(rarity: str, expected: int) -> None:
    assert rarity_color(rarity) == discord.Color(expected)


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


def test_event_list_entry_is_compact_and_human_readable() -> None:
    from app.presentation.embeds import event_list_entry

    title, details = event_list_entry(
        {
            "id": 7,
            "event_title": "Storm",
            "status": "ended",
            "is_active": False,
            "override_loot_pool": None,
            "modifiers": {
                "fish_luck_change_percent": "-30",
                "cooldown_change_percent": "0",
            },
            "version": 4,
            "updated_at": "2026-08-06T00:00:00+00:00",
            "activated_at": "2026-08-01T12:00:00+00:00",
            "deactivated_at": "2026-08-06T00:00:00+00:00",
        }
    )

    assert title == "Storm"
    assert "ID: `7`" in details
    assert "Status: Ended" in details
    assert "Version: v4" in details
    assert "**Lifecycle**" in details
    assert "**Modifiers**" in details
    assert "---" in details
    assert "Activated: <t:1785585600:f>" in details
    assert "Deactivated: <t:1785974400:f>" in details
    assert "🍀 **Fish Luck**: -30% (×0.70)" in details
    assert "Modifiers: none" not in details
    assert "updated_at" not in details
    assert "deactivated_at" not in details
    assert '"fish_luck_change_percent"' not in details


def test_event_list_entry_uses_active_flag_when_status_is_stale() -> None:
    from app.presentation.embeds import event_list_entry

    _, details = event_list_entry(
        {
            "id": 8,
            "event_title": "Reactivated",
            "is_active": True,
            "status": "ended",
            "version": 2,
            "modifiers": {},
        }
    )

    assert "Status: Active" in details


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


def test_player_inventory_embed_renders_rows_without_raw_json() -> None:
    from app.presentation.embeds import player_inventory_embed

    embed = player_inventory_embed(
        {
            "items": [
                {
                    "id": 12,
                    "item_id": "storm_rod",
                    "title": "Storm Rod",
                    "rarity": "epic",
                    "item_type": "equipment",
                    "max_durability": 150,
                    "max_charges": None,
                    "quantity": 1,
                    "slot_id": 3,
                    "current_durability": 150,
                    "current_charges": None,
                },
                {
                    "id": 13,
                    "item_id": "bait",
                    "title": "Bait",
                    "rarity": "common",
                    "item_type": "material",
                    "max_durability": None,
                    "max_charges": 5,
                    "quantity": 10,
                    "slot_id": 4,
                    "current_durability": None,
                    "current_charges": 3,
                },
            ],
            "equipped_slots": {"rod": 3},
            "max_slots": 20,
        },
        viewer="viewer1",
    )
    fields = {field.name: field.value for field in embed.fields}
    assert embed.title == "Player inventory"
    assert "viewer1" in embed.description
    assert "2/20" in embed.description
    assert "`rod` → `[3]`" in fields["Equipped"]
    assert "Storm Rod" in fields["Items"]
    assert "×1" in fields["Items"]
    assert "id `12`" in fields["Items"]
    assert "dur 150/150" in fields["Items"]
    assert "Bait" in fields["Items"]
    assert "×10" in fields["Items"]
    assert "charges 3/5" in fields["Items"]
    text = "\n".join(field.value for field in embed.fields)
    assert "{" not in text


def test_player_inventory_embed_empty_state() -> None:
    from app.presentation.embeds import player_inventory_embed

    embed = player_inventory_embed({"items": [], "equipped_slots": {}, "max_slots": 20}, viewer="v")
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Items"] == "No items."


def test_player_stats_explain_embed_renders_contributions() -> None:
    from app.presentation.embeds import player_stats_explain_embed

    result = {
        "user_twitch_id": "viewer1",
        "scope": "fishing",
        "stats": {
            "fish_luck_change_ratio": {
                "value": "0.45",
                "contributions": [
                    {
                        "operation": "add",
                        "value": "0.40",
                        "source_key": "7:fish_luck_change_ratio",
                        "label": "Storm",
                    },
                    {
                        "operation": "add",
                        "value": "0.05",
                        "source_key": "12:0",
                        "label": "Storm Rod",
                    },
                ],
            },
            "xp_gain_change_ratio": {"value": "0", "contributions": []},
        },
        "behavioral_effects": [
            {
                "type": "mass_floor",
                "protected_mass": "100",
                "source_item_key": "shield",
            }
        ],
    }
    embed = player_stats_explain_embed(result)
    fields = {field.name: field.value for field in embed.fields}
    assert embed.title == "Resolved player stats"
    assert "viewer1" in embed.description
    assert "fishing" in embed.description
    assert "add" in fields["`fish_luck_change_ratio`"]
    assert "0.40" in fields["`fish_luck_change_ratio`"]
    assert "Storm" in fields["`fish_luck_change_ratio`"]
    assert "Storm Rod" in fields["`fish_luck_change_ratio`"]
    assert "→ **0.45**" in fields["`fish_luck_change_ratio`"]
    assert "`xp_gain_change_ratio`" not in fields  # no sources -> hidden
    assert "mass_floor" in fields["Behavioral effects (1)"]
    assert "shield" in fields["Behavioral effects (1)"]
    text = "\n".join(field.value for field in embed.fields)
    assert "{" not in text


def test_player_stats_explain_embed_empty_state() -> None:
    from app.presentation.embeds import player_stats_explain_embed

    embed = player_stats_explain_embed(
        {
            "user_twitch_id": "v",
            "scope": "robbery",
            "stats": {"x": {"value": "0", "contributions": []}},
        }
    )
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Stats"] == "No modifiers resolved for this scope."


def test_reward_detail_embed_renders_reward_card() -> None:
    embed = reward_detail_embed(
        {
            "reward_id": "r1",
            "type": "fish",
            "name": "Big Trout",
            "weight": 40,
            "probability": 0.4,
            "xp": 50,
            "message": "You caught a big trout!",
            "min_mass": "1.5",
            "max_mass": "8.0",
        },
        location_id="lake",
    )
    fields = {field.name: field.value for field in embed.fields}
    assert embed.title == "Reward: Big Trout"
    assert fields["Reward ID"] == "`r1`"
    assert fields["Type"] == "Fish"
    assert fields["Location"] == "`lake`"
    assert fields["Weight"] == "40"
    assert fields["Probability"] == "40.00%"
    assert fields["XP"] == "50"
    assert fields["Message"] == "You caught a big trout!"
    assert "Mass range: +1.5 to +8 kg" in fields["Outcome details"]
    assert "min_mass" not in fields["Outcome details"]
    assert "max_mass" not in fields["Outcome details"]
    text = "\n".join(field.value for field in embed.fields)
    assert "{" not in text


def test_reward_list_entry_uses_typed_outcome_labels() -> None:
    title, details = reward_list_entry(
        {
            "reward_id": "timeout-1",
            "type": "timeout",
            "name": "Short timeout",
            "weight": 2,
            "probability": 0.05,
            "xp": 0,
            "duration": 60,
            "reason": "Test timeout",
            "message": "Please wait.",
        }
    )
    assert title == "Short timeout"
    assert "Chance: 5.00%" in details
    assert "Duration: 1 minute" in details
    assert "Reason: Test timeout" in details
    assert "duration:" not in details
