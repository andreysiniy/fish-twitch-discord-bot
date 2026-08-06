"""Discord /fish account commands (module-per-domain)."""


import discord
from discord import app_commands

from app.presentation.embeds import (
    status_embed,
)

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


def register_account_group(tree, api, sessions, fish) -> None:
        account = app_commands.Group(name="account", description="Manage your Twitch link", parent=fish)

        @account.command(name="link", description="Create a one-time Twitch authorization link")
        async def account_link(interaction: discord.Interaction) -> None:
            async def operation() -> None:
                result = await api.link_start(interaction)
                view = discord.ui.View(timeout=600)
                view.add_item(
                    discord.ui.Button(label="Authorize on Twitch", url=result["authorization_url"])
                )
                await interaction.followup.send(
                    "Open the authorization page. This link expires in 10 minutes.",
                    view=view,
                    ephemeral=True,
                )

            await _deferred(interaction, operation)

        @account.command(name="status", description="Show your Twitch link and server binding")
        async def account_status(interaction: discord.Interaction) -> None:
            async def operation() -> None:
                result = await api.status(interaction)
                await interaction.followup.send(embed=status_embed(result), ephemeral=True)

            await _deferred(interaction, operation)

        @account.command(name="unlink", description="Remove your Twitch account link")
        async def account_unlink(interaction: discord.Interaction) -> None:
            await _confirmation(
                interaction,
                "Unlink your Twitch account? Server settings will remain unchanged.",
                lambda confirmed: api.unlink(confirmed),
                "Twitch account unlinked.",
                danger=True,
            )

        @fish.command(name="link", description="Create a one-time Twitch authorization link")
        async def quick_link(interaction: discord.Interaction) -> None:
            await account_link.callback(interaction)

        @fish.command(name="status", description="Show your Twitch link and server binding")
        async def quick_status(interaction: discord.Interaction) -> None:
            await account_status.callback(interaction)

        @fish.command(name="unlink", description="Remove your Twitch account link")
        async def quick_unlink(interaction: discord.Interaction) -> None:
            await account_unlink.callback(interaction)
        return {
            "account_link": account_link,
            "account_status": account_status,
            "account_unlink": account_unlink,
        }
