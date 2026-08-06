"""Registration aggregator for all /fish command groups.

Each domain lives in its own module (``app.commands.<domain>``) per the audit;
this file only wires the groups onto the ``fish`` command tree, including the
cross-group autocomplete plumbing that several modules share.
"""

import discord
from discord import app_commands

from app.api.errors import EngineError
from app.commands.account import register_account_group
from app.commands.casts import register_casts_group
from app.commands.config import register_config_group
from app.commands.events import register_events_group
from app.commands.item_drops import register_item_drops_group
from app.commands.items import register_items_group
from app.commands.locations import register_locations_group
from app.commands.players import register_players_group
from app.commands.rewards import register_rewards_group
from app.commands.setup import register_setup_group
from app.commands.shared import *  # noqa: F401,F403  (re-exports for tests/tools)
from app.commands.shared import (  # noqa: F401  (underscore helpers used by tests)
    _json_confirmation,
    _json_embed,
    _player_modifier_preview_embed,
)

__all__ = [
    "register_commands",
    "register_account_group",
    "register_casts_group",
    "register_config_group",
    "register_events_group",
    "register_item_drops_group",
    "register_items_group",
    "register_locations_group",
    "register_players_group",
    "register_rewards_group",
    "register_setup_group",
]


def register_commands(tree, api, sessions) -> None:
    """Register the full /fish command tree."""
    fish = app_commands.Group(name="fish", description="Manage Fisher Bot")

    @fish.command(name="help", description="Show available Fisher Bot commands")
    async def help_command(interaction) -> None:
        embed = discord.Embed(title="Fisher Bot administration", color=discord.Color.blurple())
        embed.description = (
            "Use `/fish account link` first, then `/fish setup bind` in the server you manage.\n\n"
            "`account` — Twitch identity link\n"
            "`setup` — server-to-channel binding\n"
            "`config` — XP, economy, robbery, and cooldown settings\n"
            "`location` — fishing locations\n"
            "`reward` — weighted channel rewards\n"
            "`event` — channel events\n"
            "`item` — typed item definitions and effects\n"
            "`item-drop` — location item drops\n"
            "`player` — viewer inventory and stats\n"
            "`player-modifier` — per-player stat modifiers\n"
            "`player-stats` — resolved player stat explanation\n"
            "`placeholders` — message placeholder reference\n"
            "`cast` — fishing cast history, search, and statistics"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    account = register_account_group(tree, api, sessions, fish)
    register_setup_group(tree, api, sessions, fish, account_status=account.get("account_status"))
    _ = register_config_group(tree, api, sessions, fish)
    locations = register_locations_group(tree, api, sessions, fish)
    rewards = register_rewards_group(tree, api, sessions, fish)
    events = register_events_group(tree, api, sessions, fish)
    items = register_items_group(tree, api, sessions, fish)
    item_drops = register_item_drops_group(tree, api, sessions, fish)
    players = register_players_group(tree, api, sessions, fish)
    register_casts_group(tree, api, fish)
    tree.add_command(fish)

    _wire_cross_group_autocompletes(api, locations, rewards, events, items, item_drops, players)


def _wire_cross_group_autocompletes(api, locations, rewards, events, items, item_drops, players) -> None:
    """Attach shared autocompletes to commands across domain modules."""

    async def message_key_autocomplete(
        interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            result = await api.message_placeholders(interaction)
        except EngineError:
            return []
        needle = current.casefold()
        return [
            app_commands.Choice(name=item["message_key"][:100], value=item["message_key"])
            for item in result["items"]
            if needle in item["message_key"].casefold()
        ][:25]

    async def location_autocomplete(
        interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            result = await api.locations(interaction)
        except EngineError:
            return []
        needle = current.casefold()
        return [
            app_commands.Choice(
                name=f"{item['location_name']} ({item['location_id']})"[:100],
                value=item["location_id"],
            )
            for item in result["items"]
            if needle in item["location_id"].casefold()
            or needle in item["location_name"].casefold()
        ][:25]

    async def reward_autocomplete(
        interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            result = await api.rewards(interaction)
        except EngineError:
            return []
        needle = current.casefold()
        return [
            app_commands.Choice(
                name=f"{item['reward_type']} ({item['reward_id']})"[:100],
                value=item["reward_id"],
            )
            for item in result["items"]
            if needle in item["reward_id"].casefold()
        ][:25]

    async def event_autocomplete(
        interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            result = await api.events(interaction)
        except EngineError:
            return []
        needle = current.casefold()
        return [
            app_commands.Choice(name=item["event_title"][:100], value=str(item["id"]))
            for item in result["items"]
            if needle in str(item["id"]).casefold() or needle in item["event_title"].casefold()
        ][:25]

    async def item_autocomplete(
        interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        try:
            result = await api.items(interaction, include_archived=True)
        except EngineError:
            return []
        needle = current.casefold()
        return [
            app_commands.Choice(
                name=f"{entry['title']} ({entry['item_id']})"[:100],
                value=entry["item_id"],
            )
            for entry in result["items"]
            if needle in entry["item_id"].casefold()
            or needle in entry["title"].casefold()
        ][:25]

    for command in (
        locations["location_show"],
        locations["location_edit"],
        locations["location_delete"],
        rewards["reward_list"],
        rewards["reward_add"],
        rewards["reward_import_legacy"],
    ):
        command.autocomplete("location_id")(location_autocomplete)
    for command in (rewards["reward_show"], rewards["reward_edit"], rewards["reward_delete"]):
        command.autocomplete("location_id")(location_autocomplete)
        command.autocomplete("reward_id")(reward_autocomplete)
    for command in (
        events["event_show"],
        events["event_edit"],
        events["event_start"],
        events["event_delete"],
    ):
        command.autocomplete("event_id")(event_autocomplete)
    for command in (events["placeholders_show"], events["placeholders_edit"]):
        command.autocomplete("message_key")(message_key_autocomplete)
    for command in (items["item_show"], items["item_edit"], items["item_archive"]):
        command.autocomplete("item_id")(item_autocomplete)
    for command in (
        item_drops["item_drop_list"],
        item_drops["item_drop_add"],
        item_drops["item_drop_edit"],
        item_drops["item_drop_remove"],
    ):
        command.autocomplete("location_id")(location_autocomplete)
    for command in (
        item_drops["item_drop_add"],
        item_drops["item_drop_edit"],
        item_drops["item_drop_remove"],
        players["player_item_grant"],
    ):
        command.autocomplete("item_id")(item_autocomplete)
