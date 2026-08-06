import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import discord

from app.presentation.formatting import diff_lines


# Semantic palette (UI audit §7.1/§7.4): every state maps to one colour so all
# commands present info/preview/success/warning/error consistently.
def info_embed(title: str, **kwargs: Any) -> discord.Embed:
    return discord.Embed(title=title, color=discord.Color.blurple(), **kwargs)


def preview_embed(title: str, **kwargs: Any) -> discord.Embed:
    return discord.Embed(title=title, color=discord.Color.orange(), **kwargs)


def success_embed(title: str, **kwargs: Any) -> discord.Embed:
    return discord.Embed(title=title, color=discord.Color.green(), **kwargs)


def warning_embed(title: str, **kwargs: Any) -> discord.Embed:
    return discord.Embed(title=title, color=discord.Color.gold(), **kwargs)


def error_embed(title: str, **kwargs: Any) -> discord.Embed:
    return discord.Embed(title=title, color=discord.Color.red(), **kwargs)


def danger_embed(title: str, **kwargs: Any) -> discord.Embed:
    return discord.Embed(title=title, color=discord.Color.dark_red(), **kwargs)


def status_embed(status: dict[str, Any]) -> discord.Embed:
    embed = info_embed("Fisher Bot — status")
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
    embed = info_embed(f"Configuration{f' — {section}' if section else ''}")
    embed.description = f"Version: `{config['version']}`"
    values = config.get("effective", {})
    for key, value in values.items():
        embed.add_field(name=key, value=f"`{value}`", inline=True)
    return embed


def diff_embed(title: str, before: dict[str, Any], after: dict[str, Any]) -> discord.Embed:
    lines = diff_lines(before, after)
    embed = preview_embed(title)
    embed.description = "\n".join(lines) if lines else "No changes."
    return embed


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


def legacy_import_embed(result: dict[str, Any], replace_existing: bool) -> discord.Embed:
    embed = discord.Embed(
        title="Legacy reward import preview",
        description=(
            f"Mode: `{'replace' if replace_existing else 'append'}`\n"
            f"Rewards to import: `{result['imported_count']}`\n"
            f"Final reward count: `{result['final_count']}`"
        ),
        color=discord.Color.orange(),
    )
    embed.add_field(
        name="Legacy types",
        value=_count_lines(result.get("source_counts", {})),
        inline=True,
    )
    embed.add_field(
        name="Converted types",
        value=_count_lines(result.get("target_counts", {})),
        inline=True,
    )
    warnings = result.get("warnings") or []
    if warnings:
        embed.add_field(
            name="Warnings",
            value="\n".join(f"- {warning}" for warning in warnings)[:1024],
            inline=False,
        )
    return embed


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


def item_list_entry(item: dict[str, Any]) -> tuple[str, str]:
    detail_parts = []
    detail_parts.append(f"ID: `{item.get('item_id', '?')}`")
    detail_parts.append(f"Type: {item.get('item_type', '?')}")
    if item.get("equipment_slot"):
        detail_parts.append(f"Slot: {item['equipment_slot']}")
    detail_parts.append(f"Rarity: {item.get('rarity', '?')}")
    if item.get("is_active") is not None:
        detail_parts.append("Active" if item["is_active"] else "Archived")
    effect_count = len(item.get("effects") or [])
    detail_parts.append(f"{effect_count} effect(s)" if effect_count else "no effects")
    detail_parts.append(f"v{item.get('version', '?')}")
    return item.get("title") or item.get("item_id", "?"), " · ".join(detail_parts)


def item_detail_embed(item: dict[str, Any]) -> discord.Embed:
    archived = item.get("is_active") is False
    embed = info_embed(item.get("title") or item.get("item_id", "Item"))
    embed.description = item.get("description") or None
    status = "archived" if archived else "active"
    embed.add_field(name="ID", value=f"`{item.get('item_id')}`", inline=True)
    embed.add_field(name="Type", value=item.get("item_type", "?"), inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Rarity", value=item.get("rarity", "?"), inline=True)
    if item.get("equipment_slot"):
        embed.add_field(name="Slot", value=item["equipment_slot"], inline=True)
    else:
        embed.add_field(name="Stack size", value=item.get("stack_size", 1), inline=True)
    if item.get("max_durability"):
        embed.add_field(name="Durability", value=str(item["max_durability"]), inline=True)
        embed.add_field(name="Break policy", value=item.get("break_policy", "?"), inline=True)
    effects = item.get("effects") or []
    if effects:
        embed.add_field(
            name=f"Effects ({len(effects)})",
            value="\n".join("- " + _effect_one_line(effect) for effect in effects)[:1024],
            inline=False,
        )
    footer = [f"version {item.get('version')}"]
    if item.get("schema_version"):
        footer.append(f"schema {item['schema_version']}")
    embed.set_footer(text=" · ".join(footer))
    return embed


def _effect_one_line(effect: dict[str, Any]) -> str:
    effect_type = str(effect.get("type") or "?")
    details = json.dumps(
        {key: value for key, value in effect.items() if key != "type"},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"{effect_type} {details}" if details else effect_type


def item_drop_list_entry(item: dict[str, Any]) -> tuple[str, str]:
    order = (
        "id",
        "item_id",
        "title",
        "weight",
        "xp_gain",
        "quantity",
        "message",
        "version",
    )
    details = _entity_details(item, order)
    probability = item.get("drop_probability")
    if probability is not None:
        expected = item.get("expected_casts_to_drop")
        probability_part = f"Drop chance: {probability * 100:.2f}% per cast"
        if expected is not None:
            probability_part += f" (≈{expected} casts)"
        details = (probability_part + "\n" + details).rstrip("\n")
    return item["title"], details


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


def _count_lines(counts: dict[str, Any]) -> str:
    return "\n".join(f"`{key}`: {value}" for key, value in counts.items()) or "None"


def event_detail_embed(item: dict[str, Any]) -> discord.Embed:
    """Human-readable event card with v2 modifier percentages and factors."""
    modifiers = item.get("modifiers") or {}
    embed = discord.Embed(
        title=item.get("event_title") or f"Event #{item.get('id')}",
        color=discord.Color.green() if item.get("is_active") else discord.Color.blurple(),
    )
    status = item.get("status", "?")
    embed.add_field(name="Status", value=f"`{status}`", inline=True)
    embed.add_field(name="Version", value=f"v{item.get('version', '?')}", inline=True)
    if item.get("modifier_schema_version"):
        embed.add_field(
            name="Modifier schema",
            value=f"v{item['modifier_schema_version']}",
            inline=True,
        )
    if item.get("starts_at"):
        embed.add_field(name="Starts", value=f"<t:{_epoch(item['starts_at'])}:f>", inline=True)
    if item.get("ends_at"):
        embed.add_field(name="Ends", value=f"<t:{_epoch(item['ends_at'])}:f>", inline=True)
    if item.get("override_loot_pool"):
        embed.add_field(
            name="Loot pool override",
            value=f"`{item['override_loot_pool']}`",
            inline=True,
        )
    if item.get("requires_review"):
        embed.add_field(name="Review", value="⚠ requires review", inline=True)

    segments = [
        ("fish_luck_change_percent", "Fish Luck", "🍀"),
        ("positive_fish_reward_change_percent", "Good Catch", "📈"),
        ("negative_fish_reward_change_percent", "Bad Catch", "📉"),
        ("xp_gain_change_percent", "XP", "✨"),
        ("cooldown_change_percent", "Cooldown", "⏱"),
    ]
    lines = []
    for key, label, emoji in segments:
        raw = modifiers.get(key)
        if raw is None or raw == "":
            continue
        try:
            pct = Decimal(str(raw))
        except Exception:
            lines.append(f"{emoji} **{label}**: `{raw}`")
            continue
        if pct == 0:
            continue
        factor = Decimal("1") + (pct / 100)
        sign = "+" if pct >= 0 else ""
        lines.append(f"{emoji} **{label}**: {sign}{pct}% (×{factor:.2f})")
    if lines:
        embed.add_field(name="Modifiers", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Modifiers", value="No active modifiers.", inline=False)
    embed.set_footer(text=f"ID: {item.get('id')} · updated {item.get('updated_at', '?')}")
    return embed


def _epoch(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0
