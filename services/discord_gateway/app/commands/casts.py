"""Discord commands for fishing cast history and statistics.

Module-per-domain per the audit; registered from register_commands().
"""

import io
import json
from datetime import datetime, timezone

import discord
from discord import app_commands

from app.api.admin import AdminApi
from app.api.errors import EngineError
from app.presentation.formatting import format_compact_number
from app.presentation.pagination import PagedEmbedView

STATUS_COLORS = {
    "resolved": discord.Color.green(),
    "failed": discord.Color.red(),
    "cooldown_rejected": discord.Color.dark_grey(),
    "validation_rejected": discord.Color.orange(),
    "compensated": discord.Color.orange(),
}


def _short(cast_id: str) -> str:
    return cast_id[:8] if cast_id else ""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_mass(value, *, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    text = format_compact_number(value)
    if signed and not text.startswith("-"):
        try:
            if float(value) > 0:
                text = f"+{text}"
        except (TypeError, ValueError):
            pass
    return f"{text} kg"


def _fmt_outcome(outcome: dict | None) -> str:
    if not isinstance(outcome, dict):
        return "none"
    outcome_type = outcome.get("type")
    if outcome_type == "add_mass":
        return f"Add mass {_fmt_mass(outcome.get('mass'), signed=True)}"
    if outcome_type == "add_percentage_mass":
        return f"Add mass {_fmt_probability(outcome.get('percentage'))}"
    if outcome_type == "timeout":
        reason = outcome.get("reason") or "No reason"
        return f"Timeout for {outcome.get('duration', '?')} seconds ({reason})"
    if outcome_type == "nothing":
        return "Nothing"
    return str(outcome_type or "unknown").replace("_", " ").capitalize()


def _fmt_counter_actions(actions) -> str:
    if not isinstance(actions, list) or not actions:
        return "none"
    lines = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        action_type = action.get("type")
        if action_type == "timeout":
            lines.append(f"Timeout ({action.get('duration_seconds', '?')} seconds)")
        elif action_type == "add_mass":
            lines.append(f"Mass {_fmt_mass(action.get('amount'), signed=True)}")
        else:
            lines.append(str(action_type or "unknown").replace("_", " ").capitalize())
    return "; ".join(lines) or "none"


def _reward_details_lines(item: dict) -> list[str]:
    reward_type = (item.get("reward") or {}).get("reward_type")
    details = item.get("reward_details") or {}
    if reward_type == "robbery":
        robbery = details.get("robbery")
        if not isinstance(robbery, dict):
            return []
        if not robbery.get("victim_found", True):
            outcome = "No target found"
        elif robbery.get("absorbed"):
            outcome = "Blocked by protection"
        elif robbery.get("is_success"):
            outcome = "Successful"
        else:
            outcome = "Failed"
        lines = [
            f"Attacker: {item.get('username') or 'unknown'}",
            f"Victim: {robbery.get('victim_name') or 'unknown'}",
            f"Outcome: {outcome}",
            f"Stolen: {_fmt_mass(robbery.get('amount_stolen'), signed=True)}",
            f"Victim mass after: {_fmt_mass(robbery.get('victim_new_mass'))}",
            f"Success chance: {_fmt_probability(robbery.get('chance_used'))}",
            f"Robbery roll: {_fmt_roll(robbery.get('roll'))}",
            f"Counter effects: {_fmt_counter_actions(robbery.get('counter_actions'))}",
        ]
        return lines

    if reward_type == "russian_roulette":
        roulette = details.get("roulette")
        if not isinstance(roulette, dict):
            return []
        outcome = "Loaded chamber (hit)" if roulette.get("is_hit") else "Empty chamber (safe)"
        selected_outcome = roulette.get("penalty") if roulette.get("is_hit") else roulette.get("reward")
        return [
            f"Outcome: {outcome}",
            f"Loaded chambers: {roulette.get('bullets', '?')} / {roulette.get('chambers', '?')}",
            f"Success chance: {_fmt_probability(roulette.get('success_chance'))}",
            f"Roulette roll: {_fmt_roll(roulette.get('roll'))}",
            f"Applied result: {_fmt_outcome(selected_outcome)}",
            f"Mass change: {_fmt_mass(roulette.get('mass_delta'), signed=True)}",
            f"Message: {roulette.get('message') or 'none'}",
        ]
    return []


def cast_detail_embed(item: dict) -> discord.Embed:
    color = STATUS_COLORS.get(item.get("status"), discord.Color.blurple())
    embed = discord.Embed(
        title=f"Fishing cast {_short(item.get('cast_id', ''))}",
        color=color,
    )
    embed.add_field(
        name="Status",
        value=item.get("status", "?"),
        inline=True,
    )
    embed.add_field(
        name="Time",
        value=(item.get("requested_at") or "?")[:19],
        inline=True,
    )
    embed.add_field(
        name="Viewer",
        value=item.get("username") or "?",
        inline=True,
    )
    embed.add_field(
        name="Location",
        value=item.get("location_name") or item.get("location_id") or "?",
        inline=True,
    )
    embed.add_field(
        name="Event",
        value=(item.get("event") or {}).get("title") or "—",
        inline=True,
    )

    state = item.get("state") or {}
    embed.add_field(
        name="Mass",
        value=(
            f"`{state.get('mass_before')} → {state.get('mass_after')}` "
            f"({state.get('mass_delta_applied')})"
        ),
        inline=False,
    )
    embed.add_field(
        name="XP / Level",
        value=(
            f"{state.get('xp_before')} → {state.get('xp_after')} XP · "
            f"Lv {state.get('level_before')} → {state.get('level_after')} "
            f"({state.get('xp_gained')} XP)"
        ),
        inline=False,
    )

    reward = item.get("reward") or {}
    reward_lines = [
        f"`{reward.get('reward_type') or '?'}` "
        f"`{reward.get('reward_id') or ''}`",
        f"probability: {_fmt_probability(reward.get('probability'))} • "
        f"roll: {_fmt_roll(reward.get('roll'))}",
    ]
    if reward.get("weight") or reward.get("total_weight"):
        reward_lines.append(
            f"weight: {_fmt_weight(reward.get('weight'))} / "
            f"{_fmt_weight(reward.get('total_weight'))}"
        )
    embed.add_field(name="Reward", value="\n".join(reward_lines), inline=False)

    reward_details = _reward_details_lines(item)
    if reward_details:
        embed.add_field(name="Reward details", value="\n".join(reward_details), inline=False)

    drops = item.get("items") or []
    if drops:
        lines = [
            f"{d.get('title')} ×{d.get('quantity_granted')} [{d.get('grant_status')}]"
            for d in drops
        ]
        embed.add_field(name="Item drops", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Item drops", value="none", inline=False)
    return embed


def cast_stats_embed(stats: dict) -> discord.Embed:
    embed = discord.Embed(
        title="Fishing statistics",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Casts", value=str(stats.get("casts", 0)), inline=True)
    embed.add_field(
        name="Unique viewers", value=str(stats.get("unique_players", 0)), inline=True
    )
    embed.add_field(name="Failures", value=str(stats.get("failures", 0)), inline=True)
    embed.add_field(
        name="Mass gained",
        value=_fmt_num(stats.get("mass_positive", 0)),
        inline=True,
    )
    embed.add_field(
        name="Mass lost",
        value=_fmt_num(stats.get("mass_negative", 0)),
        inline=True,
    )
    embed.add_field(name="XP granted", value=str(stats.get("total_xp", 0)), inline=True)
    expected = stats.get("items_expected", 0)
    actual = stats.get("items_actual", 0)
    rate = (actual / expected) if expected else 0
    embed.add_field(
        name="Items",
        value=f"{actual} actual / {expected:.1f} expected ({rate:.2%})",
        inline=False,
    )
    return embed


def _fmt_num(value) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_probability(value) -> str:
    """Ratio (0-1) rounded to a human percentage, e.g. 0.0191 -> '1.91%'."""
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_roll(value) -> str:
    """Random roll rounded for display; the raw value stays in the backend."""
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_weight(value) -> str:
    """Weight shown without its fractional part."""
    try:
        return f"{float(value):.0f}"
    except (TypeError, ValueError):
        return "n/a"


def _allow_owner_only() -> bool:
    return True


async def _deferred(interaction: discord.Interaction, operation) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        await operation()
    except EngineError as error:
        await interaction.followup.send(
            f"{error.message}", ephemeral=True
        )
    except Exception:
        await interaction.followup.send(
            "Something went wrong while loading fishing history.",
            ephemeral=True,
        )


def register_casts_group(
    tree: app_commands.CommandTree,
    api: AdminApi,
    parent: app_commands.Group,
) -> app_commands.Group:
    cast = app_commands.Group(name="cast", description="Fishing cast history", parent=parent)

    @cast.command(name="recent", description="Show recent fishing casts")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Resolved", value="resolved"),
            app_commands.Choice(name="Failed", value="failed"),
            app_commands.Choice(name="Cooldown", value="cooldown_rejected"),
        ]
    )
    @app_commands.describe(viewer="Viewer Twitch username; omit for all viewers")
    async def cast_recent(
        interaction: discord.Interaction,
        viewer: str | None = None,
        location: str | None = None,
        status: app_commands.Choice[str] | None = None,
        limit: int = 20,
    ) -> None:
        _allow_owner_only()

        async def operation() -> None:
            result = await api.recent_casts(
                interaction,
                limit=max(5, min(limit, 25)),
                username=viewer,
                location_id=location,
                status=status.value if status else None,
            )
            view = PagedEmbedView(
                interaction.user.id,
                "Recent fishing casts",
                result.get("items", []),
                embed_builder=cast_detail_embed,
            )
            await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

        await _deferred(interaction, operation)

    @cast.command(name="show", description="Show details for one fishing cast")
    async def cast_show(
        interaction: discord.Interaction,
        cast_id: str,
        technical: bool = False,
    ) -> None:
        async def operation() -> None:
            item = await api.cast_detail(interaction, cast_id, include_technical=technical)
            embed = cast_detail_embed(item)
            if technical and item.get("technical"):
                embed.add_field(
                    name="RNG trace",
                    value=str(item["technical"].get("rng_trace"))[:1000] or "—",
                    inline=False,
                )
            await interaction.followup.send(embed=embed, ephemeral=True)

        await _deferred(interaction, operation)

    @cast.command(name="stats", description="Show channel fishing statistics")
    async def cast_stats(interaction: discord.Interaction) -> None:
        async def operation() -> None:
            stats = await api.cast_stats(interaction)
            await interaction.followup.send(
                embed=cast_stats_embed(stats), ephemeral=True
            )

        await _deferred(interaction, operation)

    @cast.command(name="search", description="Search fishing casts by filters")
    @app_commands.describe(
        viewer="Viewer Twitch username; omit for all viewers",
        username="Also filter by viewer username",
    )
    async def cast_search(
        interaction: discord.Interaction,
        viewer: str | None = None,
        username: str | None = None,
        status: app_commands.Choice[str] | None = None,
        location: str | None = None,
        reward_type: str | None = None,
        item_id: str | None = None,
        has_item: bool | None = None,
        min_mass: float | None = None,
        max_mass: float | None = None,
        limit: int = 20,
    ) -> None:
        _allow_owner_only()

        async def operation() -> None:
            result = await api.search_casts(
                interaction,
                username=viewer or username,
                status=status.value if status else None,
                location_id=location,
                reward_type=reward_type,
                item_id=item_id,
                has_item=has_item,
                min_mass_delta=min_mass,
                max_mass_delta=max_mass,
                limit=max(5, min(limit, 25)),
            )
            view = PagedEmbedView(
                interaction.user.id,
                "Fishing cast search",
                result.get("items", []),
                embed_builder=cast_detail_embed,
            )
            await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

        await _deferred(interaction, operation)

    @cast.command(name="export", description="Export the raw fishing cast journal as JSON")
    @app_commands.describe(viewer="Viewer Twitch username; omit for all viewers")
    async def cast_export(
        interaction: discord.Interaction,
        viewer: str | None = None,
        status: app_commands.Choice[str] | None = None,
    ) -> None:
        _allow_owner_only()

        async def operation() -> None:
            result = await api.recent_casts(
                interaction,
                limit=25,
                username=viewer,
                status=status.value if status else None,
            )
            rows = result.get("items", [])
            payload = {
                "exported_at": _utcnow_iso(),
                "channel": interaction.guild.name if interaction.guild else None,
                "count": len(rows),
                "casts": rows,
            }
            raw = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
            file = discord.File(io.StringIO(raw), filename="casts_export.json")
            await interaction.followup.send(
                f"Exported {len(rows)} fishing cast record(s) as JSON.",
                file=file,
                ephemeral=True,
            )

        await _deferred(interaction, operation)

    return cast
