from typing import Any

import discord

from app.presentation.formatting import diff_lines


def status_embed(status: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(title="Fisher Bot — status", color=discord.Color.blue())
    twitch = status.get("twitch")
    binding = status.get("binding")
    embed.add_field(
        name="Twitch",
        value=(f"{twitch['login']} (`{twitch['id']}`)" if twitch else "Not linked"),
        inline=False,
    )
    embed.add_field(
        name="Server",
        value=(
            f"{binding['channel_name']} (`{binding['channel_twitch_id']}`)"
            if binding
            else "Not configured"
        ),
        inline=False,
    )
    return embed


def config_embed(config: dict[str, Any], section: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title=f"Configuration{f' — {section}' if section else ''}",
        description=f"Version: `{config['version']}`",
        color=discord.Color.blurple(),
    )
    values = config.get("effective", {})
    for key, value in values.items():
        embed.add_field(name=key, value=f"`{value}`", inline=True)
    return embed


def diff_embed(title: str, before: dict[str, Any], after: dict[str, Any]) -> discord.Embed:
    lines = diff_lines(before, after)
    return discord.Embed(
        title=title,
        description="\n".join(lines) if lines else "No changes.",
        color=discord.Color.orange(),
    )
