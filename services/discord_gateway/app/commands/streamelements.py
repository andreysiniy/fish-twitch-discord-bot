"""Discord StreamElements connection and points economy commands."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import discord
from discord import app_commands

from app.api.errors import EngineError
from app.commands.shared import _confirmation, _deferred, _send_error
from app.presentation.formatting import format_compact_number
from app.presentation.pagination import PagedEmbedView

ECONOMY_OPERATION_STATUS_COLORS = {
    "completed": discord.Color.green(),
    "external_applied": discord.Color.green(),
    "failed": discord.Color.red(),
    "dead_letter": discord.Color.red(),
    "compensated": discord.Color.orange(),
    "reconciliation_required": discord.Color.orange(),
    "pending": discord.Color.gold(),
    "queued": discord.Color.gold(),
    "processing": discord.Color.gold(),
    "external_pending": discord.Color.gold(),
}


def _operation_short_id(operation_id: object) -> str:
    value = str(operation_id or "")
    return value[:8] or "unknown"


def _operation_number(value: object, *, signed: bool = False, suffix: str = "") -> str:
    """Format economy values without exposing Decimal scale noise."""
    if value is None or value == "":
        return "n/a"
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if not decimal.is_finite():
        return str(value)
    text = format_compact_number(decimal)
    if signed and decimal > 0:
        text = f"+{text}"
    return f"{text}{suffix}"


def _operation_timestamp(value: object) -> str:
    """Use Discord's localized timestamp for operation lifecycle fields."""
    if not value:
        return "n/a"
    raw = str(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return f"<t:{int(parsed.timestamp())}:f>"
    except (TypeError, ValueError, OverflowError):
        return raw[:19]


def _operation_state_label(state: object) -> str:
    return str(state or "unknown").replace("_", " ").title()


def _operation_error_text(item: dict) -> str | None:
    code = item.get("error_code")
    reason = item.get("last_error") or item.get("reconciliation_reason")
    if not code and not reason:
        return None
    label = str(code or "Operation issue").replace("_", " ").title()
    if not reason:
        return label
    text = str(reason).strip()
    # Provider errors can be large; the Discord card should remain actionable
    # without dumping a raw response payload into the administrative UI.
    if len(text) > 900:
        text = f"{text[:897]}..."
    return f"{label}: {text}"


def economy_operation_detail_embed(item: dict) -> discord.Embed:
    """Render one StreamElements operation as a readable audit card."""
    state = str(item.get("state") or "unknown")
    embed = discord.Embed(
        title=f"Economy operation {_operation_short_id(item.get('operation_id'))}",
        color=ECONOMY_OPERATION_STATUS_COLORS.get(state, discord.Color.blurple()),
    )
    embed.add_field(name="Status", value=_operation_state_label(state), inline=True)
    embed.add_field(
        name="Type", value=str(item.get("operation_type") or "unknown").title(), inline=True
    )
    embed.add_field(name="Time", value=_operation_timestamp(item.get("requested_at")), inline=True)
    embed.add_field(name="Viewer", value=item.get("username") or "unknown", inline=True)

    mass_lines: list[str] = []
    if item.get("player_mass_before") is not None or item.get("player_mass_after") is not None:
        mass_lines.append(
            f"{_operation_number(item.get('player_mass_before'), suffix=' kg')} → "
            f"{_operation_number(item.get('player_mass_after'), suffix=' kg')}"
        )
    if item.get("mass_delta") is not None:
        mass_lines.append(
            f"Change: {_operation_number(item.get('mass_delta'), signed=True, suffix=' kg')}"
        )
    if item.get("mass_effective") is not None:
        mass_lines.append(f"Effective: {_operation_number(item.get('mass_effective'), suffix=' kg')}")
    embed.add_field(name="Mass", value="\n".join(mass_lines) or "n/a", inline=False)

    points_lines = [
        f"Change: {_operation_number(item.get('points_delta'), signed=True, suffix=' points')}",
        f"Calculated: {_operation_number(item.get('points_calculated'), suffix=' points')}",
    ]
    if item.get("provider_balance_before") is not None or item.get("provider_balance_after") is not None:
        points_lines.append(
            f"Balance: {_operation_number(item.get('provider_balance_before'))} → "
            f"{_operation_number(item.get('provider_balance_after'))} points"
        )
    if item.get("provider_points_cap") is not None:
        points_lines.append(f"Cap: {_operation_number(item.get('provider_points_cap'))} points")
    if (
        item.get("provider_points_headroom_before") is not None
        or item.get("provider_points_headroom_after") is not None
    ):
        points_lines.append(
            f"Headroom: {_operation_number(item.get('provider_points_headroom_before'))} → "
            f"{_operation_number(item.get('provider_points_headroom_after'))} points"
        )
    embed.add_field(name="Points", value="\n".join(points_lines), inline=False)

    pricing_lines = []
    if item.get("rate"):
        pricing_lines.append(f"Rate: {_operation_number(item.get('rate'), suffix=' points/kg')}")
    if item.get("pricing_mode"):
        pricing_lines.append(
            f"Pricing mode: {str(item.get('pricing_mode')).replace('_', ' ').title()}"
        )
    if item.get("provider_channel_id"):
        pricing_lines.append(f"Provider channel: `{item['provider_channel_id']}`")
    if item.get("started_at"):
        pricing_lines.append(f"Started: {_operation_timestamp(item.get('started_at'))}")
    if item.get("completed_at"):
        pricing_lines.append(f"Completed: {_operation_timestamp(item.get('completed_at'))}")
    if item.get("attempts") is not None:
        pricing_lines.append(f"Attempts: {item.get('attempts')}")
    if item.get("external_applied") is not None:
        pricing_lines.append(
            f"Provider mutation: {'applied' if item.get('external_applied') else 'not applied'}"
        )
    if pricing_lines:
        embed.add_field(name="Processing", value="\n".join(pricing_lines), inline=False)

    error_text = _operation_error_text(item)
    if error_text:
        embed.add_field(name="Issue", value=error_text, inline=False)
    return embed


def _is_effective_switch_enabled(settings: dict, field: str) -> bool:
    """A disabled conversions switch makes both market directions unavailable."""
    return bool(settings.get("enabled")) and bool(settings.get(field))


class StreamElementsConnectModal(discord.ui.Modal, title="Connect StreamElements"):
    token = discord.ui.TextInput(
        label="StreamElements JWT",
        style=discord.TextStyle.paragraph,
        min_length=20,
        # Discord text inputs reject values above 4000 characters.
        max_length=4000,
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
    buy_points_per_kg = discord.ui.TextInput(
        label="Buy rate (points per kg)", required=True, max_length=18
    )
    sell_points_per_kg = discord.ui.TextInput(
        label="Sell rate (points per kg)", required=True, max_length=18
    )
    minimum = discord.ui.TextInput(label="Minimum mass (kg)", required=True, max_length=18)
    maximum = discord.ui.TextInput(
        label="Maximum mass (kg)",
        placeholder="Enter a number or MAX_NUMBER",
        required=True,
        max_length=18,
    )

    def __init__(self, api, current: dict):
        super().__init__(timeout=600)
        self.api = api
        self.current = current
        self.buy_points_per_kg.default = format_compact_number(
            current.get("buy_points_per_kg", "120")
        )
        self.sell_points_per_kg.default = format_compact_number(
            current.get("sell_points_per_kg", "100")
        )
        self.minimum.default = format_compact_number(current.get("min_transaction_mass", "0.01"))
        current_maximum = current.get("max_transaction_mass", "2147483647")
        if format_compact_number(current_maximum) == "2147483647":
            self.maximum.default = "MAX_NUMBER"
        else:
            self.maximum.default = format_compact_number(current_maximum)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self.api.patch_economy_settings(
                interaction,
                {
                    "expected_version": int(self.current["version"]),
                    "buy_points_per_kg": str(self.buy_points_per_kg.value),
                    "sell_points_per_kg": str(self.sell_points_per_kg.value),
                    "min_transaction_mass": str(self.minimum.value),
                    "max_transaction_mass": str(self.maximum.value),
                },
            )
            await interaction.followup.send(
                "Rates and limits updated. Use the controls below to change economy switches.",
                view=EconomySwitchesView(self.api, result),
                ephemeral=True,
            )
        except (EngineError, ValueError) as error:
            await _send_error(interaction, error)


class EconomySwitchesView(discord.ui.View):
    def __init__(self, api, current: dict):
        super().__init__(timeout=600)
        self.api = api
        self.current = dict(current)
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        self.enabled_button.label = f"Conversions: {'On' if self.current.get('enabled') else 'Off'}"
        self.buy_button.label = (
            f"Buying: {'On' if _is_effective_switch_enabled(self.current, 'buy_enabled') else 'Off'}"
        )
        self.sell_button.label = (
            f"Selling: {'On' if _is_effective_switch_enabled(self.current, 'sell_enabled') else 'Off'}"
        )

    async def _toggle(self, interaction: discord.Interaction, field: str) -> None:
        try:
            result = await self.api.patch_economy_settings(
                interaction,
                {
                    "expected_version": int(self.current["version"]),
                    field: not bool(self.current.get(field)),
                },
            )
            self.current = dict(result)
            self._refresh_labels()
            await interaction.response.edit_message(view=self)
        except (EngineError, ValueError) as error:
            await _send_error(interaction, error)

    @discord.ui.button(label="Conversions", style=discord.ButtonStyle.primary)
    async def enabled_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "enabled")

    @discord.ui.button(label="Buying", style=discord.ButtonStyle.secondary)
    async def buy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "buy_enabled")

    @discord.ui.button(label="Selling", style=discord.ButtonStyle.secondary)
    async def sell_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle(interaction, "sell_enabled")


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
    embed.add_field(
        name="Last check", value=str(result.get("last_check_at", "Never")), inline=True
    )
    embed.add_field(
        name="Next check", value=str(result.get("next_validation_at", "Not scheduled")), inline=True
    )
    embed.add_field(
        name="Failures", value=str(result.get("consecutive_failures", 0)), inline=True
    )
    if result.get("validation_latency_ms") is not None:
        embed.add_field(
            name="Probe latency",
            value=f"{result['validation_latency_ms']} ms",
            inline=True,
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
            view = PagedEmbedView(
                interaction.user.id,
                "Recent economy operations",
                result.get("items", []),
                embed_builder=economy_operation_detail_embed,
            )
            await interaction.followup.send(
                embed=view.embed(),
                view=view,
                ephemeral=True,
            )

        await _deferred(interaction, operation)

    return {"streamelements": group}
