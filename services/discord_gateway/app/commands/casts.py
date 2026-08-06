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


def cast_list_formatter(item: dict) -> tuple[str, str]:
    name = item.get("username") or item.get("cast_id", "?")
    ts = item.get("requested_at") or ""
    time_short = ts[11:19] if len(ts) >= 19 else ts
    mass = item.get("mass_label") or ""
    xp = int(item.get("xp_gained") or 0)
    location = item.get("location_id") or ""
    return (
        name,
        f"{time_short} • {location}\n"
        f"mass: {mass} • XP: {xp} • status: {item.get('status')}\n"
        f"Cast: {_short(item.get('cast_id', ''))}",
    )


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
    embed.add_field(
        name="Reward",
        value=(
            f"`{reward.get('reward_type') or '?'}` "
            f"`{reward.get('reward_id') or ''}`\n"
            f"probability: {reward.get('probability') or '—'} • "
            f"roll: {reward.get('roll') or '—'}"
        ),
        inline=False,
    )

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
                cast_list_formatter,
                page_size=10,
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
                cast_list_formatter,
                page_size=10,
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
