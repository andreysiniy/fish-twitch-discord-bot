import json
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


def reward_list_entry(item: dict[str, Any]) -> tuple[str, str]:
    title = item.get("name") or item["type"].replace("_", " ").title()
    order = (
        "reward_id",
        "type",
        "name",
        "weight",
        "probability",
        "xp",
        "message",
    )
    return title, _entity_details(item, order, probability_key="probability")


def location_list_entry(item: dict[str, Any]) -> tuple[str, str]:
    order = (
        "location_id",
        "location_name",
        "items_drop_rate",
        "requirements",
        "reward_count",
        "version",
    )
    return item["location_name"], _entity_details(item, order)


def event_list_entry(item: dict[str, Any]) -> tuple[str, str]:
    order = (
        "id",
        "event_title",
        "is_active",
        "override_loot_pool",
        "modifiers",
        "version",
        "updated_at",
    )
    return item["event_title"], _entity_details(item, order)


def placeholder_help_embeds(
    items: list[dict[str, Any]],
    message_key: str | None = None,
) -> list[discord.Embed]:
    if message_key:
        normalized = message_key.strip().lower()
        item = next((entry for entry in items if entry["message_key"] == normalized), None)
        if item is None:
            raise ValueError(f"Unknown message key: {message_key}")
        embed = discord.Embed(
            title=f"Message placeholders: {normalized}",
            color=discord.Color.blurple(),
        )
        if item.get("default_message"):
            embed.add_field(
                name="Default message",
                value=item["default_message"][:1024],
                inline=False,
            )
        placeholders = item["placeholders"]
        if not placeholders:
            embed.add_field(
                name="Placeholders",
                value="This message does not use placeholders.",
                inline=False,
            )
        for placeholder in placeholders:
            embed.add_field(
                name=f"{{{placeholder['name']}}}",
                value=placeholder["description"],
                inline=False,
            )
        return [embed]

    embeds = []
    for offset in range(0, len(items), 15):
        embed = discord.Embed(
            title="Message placeholder reference",
            description=(
                "Use `/fish placeholders show message_key:<key>` for descriptions. "
                "Placeholders that are not listed for a message are left unchanged."
            ),
            color=discord.Color.blurple(),
        )
        for item in items[offset : offset + 15]:
            names = ", ".join(
                f"`{{{placeholder['name']}}}`" for placeholder in item["placeholders"]
            )
            embed.add_field(
                name=item["message_key"],
                value=names or "No placeholders.",
                inline=False,
            )
        embed.set_footer(text=f"Messages {offset + 1}-{min(offset + 15, len(items))}")
        embeds.append(embed)
    return embeds


def _entity_details(
    item: dict[str, Any],
    preferred_order: tuple[str, ...],
    *,
    probability_key: str | None = None,
) -> str:
    ordered_keys = [key for key in preferred_order if key in item]
    ordered_keys.extend(sorted(set(item) - set(ordered_keys)))
    lines = []
    for key in ordered_keys:
        value = item[key]
        if key == probability_key:
            rendered = f"{float(value):.2%}"
        else:
            rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines)
