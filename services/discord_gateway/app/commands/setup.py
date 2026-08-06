"""Discord /fish setup commands (module-per-domain)."""


import discord
from discord import app_commands


from app.commands.shared import (  # noqa: F401  (shared helpers)
    BREAK_POLICY_CHOICES,
    EQUIPMENT_SLOT_CHOICES,
    ITEM_TYPE_CHOICES,
    MODIFIER_OPERATION_CHOICES,
    MODIFIER_SCOPE_CHOICES,
    RARITY_CHOICES,
    REWARD_CHOICES,
    SECTION_CHOICES,
    STAT_KEY_CHOICES,
    _confirmation,
    _deferred,
    _error_text,
    _item_payload,
    _json_confirmation,
    _json_embed,
    _mutation_response,
    _parse_effects,
    _player_modifier_preview_embed,
    _send_error,
    _send_json_embed,
    _session,
    _simple_mutation,
)


def register_setup_group(tree, api, sessions, fish, account_status=None) -> None:
        setup = app_commands.Group(name="setup", description="Bind this Discord server", parent=fish)

        @setup.command(name="status", description="Show the current server binding")
        async def setup_status(interaction: discord.Interaction) -> None:
            if account_status is not None:
                await account_status.callback(interaction)

        @setup.command(name="bind", description="Bind this server to your Twitch channel")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def setup_bind(interaction: discord.Interaction) -> None:
            await _simple_mutation(interaction, lambda: api.setup(interaction), "Server binding saved.")

        @setup.command(name="replace", description="Replace the existing server binding")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def setup_replace(interaction: discord.Interaction) -> None:
            await _confirmation(
                interaction,
                "Replace this server's Twitch channel binding?",
                lambda confirmed: api.setup(confirmed, replace=True),
                "Server binding replaced.",
                danger=True,
            )

        @setup.command(name="remove", description="Remove the server binding")
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        async def setup_remove(interaction: discord.Interaction) -> None:
            await _confirmation(
                interaction,
                "Remove this server's Twitch channel binding?",
                lambda confirmed: api.setup_remove(confirmed),
                "Server binding removed.",
                danger=True,
            )
        return {
            "setup_status": setup_status,
            "setup_bind": setup_bind,
            "setup_replace": setup_replace,
            "setup_remove": setup_remove,
        }
