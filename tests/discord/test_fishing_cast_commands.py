"""Unit tests for the Discord fishing cast history commands."""

import discord
from app.commands.casts import (
    cast_detail_embed,
    cast_list_formatter,
    cast_stats_embed,
    register_casts_group,
)


def test_cast_list_formatter_compacts_fields() -> None:
    name, value = cast_list_formatter(
        {
            "cast_id": "0198f72f-4bc5-7e90-9081-e7bf4df21d56",
            "username": "viewer_one",
            "requested_at": "2026-08-04T08:42:15+00:00",
            "mass_label": "+29.40",
            "xp_gained": 20,
            "location_id": "abyss",
            "status": "resolved",
        }
    )
    assert name == "viewer_one"
    assert "abyss" in value
    assert "+29.40" in value
    assert "Cast: 0198f72f" in value


def test_cast_list_formatter_handles_empty_fields() -> None:
    name, value = cast_list_formatter({"cast_id": "abc123"})
    assert name == "abc123"
    assert value


def test_cast_detail_embed_status_color() -> None:
    embed = cast_detail_embed(
        {
            "cast_id": "0198f72f-4bc5-7e90-9081-e7bf4df21d56",
            "status": "resolved",
            "username": "viewer_one",
            "location_id": "abyss",
            "state": {
                "mass_before": "100.00",
                "mass_after": "129.40",
                "mass_delta_applied": "29.40",
                "xp_before": 100,
                "xp_after": 120,
                "xp_gained": 20,
                "level_before": 4,
                "level_after": 4,
            },
            "reward": {"reward_type": "fish", "reward_id": "reward-fish-20pct"},
            "items": [],
        }
    )
    assert embed.color == discord.Color.green()
    fields = {f.name: f.value for f in embed.fields}
    assert "Viewer" in fields
    assert "100.00 → 129.40" in fields["Mass"]


def test_cast_stats_embed_computes_drop_rate() -> None:
    embed = cast_stats_embed(
        {
            "casts": 4820,
            "unique_players": 183,
            "failures": 3,
            "mass_positive": 1240500,
            "mass_negative": 312400,
            "total_xp": 28920,
            "items_actual": 282,
            "items_expected": 289.4,
        }
    )
    fields = {f.name: f.value for f in embed.fields}
    assert "282 actual / 289.4 expected" in fields["Items"]
    assert fields["Casts"] == "4820"


def test_register_casts_group_creates_subcommands() -> None:
    class FakeTree:
        pass

    tree = FakeTree()
    api = object()
    parent = discord.app_commands.Group(name="fish", description="Manage Fisher Bot")
    group = register_casts_group(tree, api, parent)  # type: ignore[arg-type]
    assert group.name == "cast"
    names = {cmd.name for cmd in group.commands}
    assert {"recent", "show", "stats"} <= names
