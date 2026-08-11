"""Discord StreamElements connection and points economy commands."""

from __future__ import annotations

import discord
from discord import app_commands

from app.api.errors import EngineError
from app.commands.shared import _confirmation, _deferred, _send_error


class StreamElementsConnectModal(discord.ui.Modal, title="Connect StreamElements"):
    token = discord.ui.TextInput(
        label="StreamElements JWT",
        style=discord.TextStyle.paragraph,
        min_length=20,
        max_length=4096,
        placeholder="Paste the token once; it is sent directly to the game engine.",
        required=True,
    )

    def __init__(self, api):
        super().__init__(timeout=600)
        self.api = api

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self.api.streamelements_connect(interaction, str(self.token.value))
            await interaction.followup.send(
                f"Connected StreamElements channel `{result.get('provider_channel_id', 'unknown')}`. "
                "The token was not retained by Discord.",
                ephemeral=True,
            )
        except EngineError as error:
            await _send_error(interaction, error)


class EconomySettingsModal(discord.ui.Modal, title="Economy settings"):
    points_per_kg = discord.ui.TextInput(label="Points per kg", required=True, max_length=18)
    minimum = discord.ui.TextInput(label="Minimum mass (kg)", required=True, max_length=18)
    maximum = discord.ui.TextInput(label="Maximum mass (kg)", required=True, max_length=18)

    def __init__(self, api, current: dict):
        super().__init__(timeout=600)
        self.api = api
        self.current = current
        self.points_per_kg.default = str(current.get("buy_points_per_kg", "1000"))
        self.minimum.default = str(current.get("min_transaction_mass", "0.01"))
        self.maximum.default = str(current.get("max_transaction_mass", "1000"))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.api.patch_economy_settings(
                interaction,
                {
                    "expected_version": int(self.current["version"]),
                    "pricing_mode": "single_rate",
                    "points_per_kg": str(self.points_per_kg.value),
                    "min_transaction_mass": str(self.minimum.value),
                    "max_transaction_mass": str(self.maximum.value),
                },
            )
            await interaction.followup.send("Economy settings updated.", ephemeral=True)
        except (EngineError, ValueError) as error:
            await _send_error(interaction, error)


def _status_embed(result: dict) -> discord.Embed:
    color = discord.Color.green() if result.get("status") == "connected" else discord.Color.orange()
    embed = discord.Embed(title="StreamElements integration", color=color)
    embed.add_field(name="Status", value=str(result.get("status", "unknown")).title(), inline=True)
    embed.add_field(
        name="Provider channel",
        value=str(result.get("provider_channel_id", "Unknown")),
        inline=True,
    )
    embed.add_field(
        name="Last validated", value=str(result.get("last_validated_at", "Never")), inline=False
    )
    if result.get("last_error_code"):
        embed.add_field(name="Last error", value=f"`{result['last_error_code']}`", inline=False)
    return embed


def register_streamelements_group(tree, api, sessions, fish):
    group = app_commands.Group(
        name="streamelements", description="Manage StreamElements points integration", parent=fish
    )

    @group.command(name="status", description="Show StreamElements connection status")
    async def status(interaction: discord.Interaction):
        async def operation():
            await interaction.followup.send(
                embed=_status_embed(await api.streamelements_status(interaction)), ephemeral=True
            )

        await _deferred(interaction, operation)

    @group.command(name="connect", description="Connect a StreamElements JWT")
    async def connect(interaction: discord.Interaction):
        await interaction.response.send_modal(StreamElementsConnectModal(api))

    @group.command(name="test", description="Validate the connected StreamElements account")
    async def test(interaction: discord.Interaction):
        async def operation():
            result = await api.streamelements_test(interaction)
            await interaction.followup.send(
                f"StreamElements test passed at {result.get('last_validated_at', 'now')}.",
                ephemeral=True,
            )

        await _deferred(interaction, operation)

    @group.command(name="disconnect", description="Disable StreamElements conversions")
    async def disconnect(interaction: discord.Interaction):
        await _confirmation(
            interaction,
            "Disconnect StreamElements? Pending operations will remain available for reconciliation.",
            lambda confirmed: api.streamelements_disconnect(confirmed),
            "StreamElements conversions disabled.",
            danger=True,
        )

    @group.command(
        name="settings", description="Configure points per kilogram and transaction limits"
    )
    async def settings(interaction: discord.Interaction):
        async def operation():
            await interaction.response.send_modal(
                EconomySettingsModal(api, await api.economy_settings(interaction))
            )

        try:
            await operation()
        except (EngineError, ValueError) as error:
            await _send_error(interaction, error)

    @group.command(name="operations", description="Show recent economy operations")
    async def operations(interaction: discord.Interaction):
        async def operation():
            result = await api.economy_operations(interaction)
            embed = discord.Embed(title="Recent economy operations", color=discord.Color.blurple())
            lines = []
            for item in result.get("items", []):
                line = f"`{item.get('operation_id', '')[:8]}` {item.get('operation_type', '').upper()} - {item.get('state', '')} - {item.get('mass_delta', '0')} kg / {item.get('points_delta', 0)} points"
                if item.get("provider_points_headroom_before") is not None:
                    line += f"\n  Balance: {item.get('provider_balance_before')} / {item.get('provider_points_cap')} (headroom {item.get('provider_points_headroom_before')})"
                if item.get("error_code"):
                    line += f"\n  Reason: `{item['error_code']}`"
                lines.append(line)
            embed.description = "\n".join(lines) or "No economy operations found."
            await interaction.followup.send(embed=embed, ephemeral=True)

        await _deferred(interaction, operation)

    return {"streamelements": group}
