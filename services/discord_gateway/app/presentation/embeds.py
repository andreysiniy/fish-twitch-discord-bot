import json
from datetime import datetime
from decimal import Decimal
from typing import Any

import discord

from app.domain.item_effect_registry import describe_effect
from app.presentation.formatting import diff_lines


RARITY_COLORS = {
    "common": discord.Color(0x95A5A6),
    "rare": discord.Color(0x3498DB),
    "epic": discord.Color(0x9B59B6),
    "legendary": discord.Color(0xF1C40F),
}


def rarity_color(rarity: Any) -> discord.Color:
    """Return the embed accent for an item rarity."""
    return RARITY_COLORS.get(str(rarity or "").casefold(), discord.Color.blurple())


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


def item_detail_embed(item: dict[str, Any], *, effects_value: str | None = None) -> discord.Embed:
    archived = item.get("is_active") is False
    embed = discord.Embed(
        title=item.get("title") or item.get("item_id", "Item"),
        color=rarity_color(item.get("rarity")),
    )
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
    if item.get("max_charges"):
        embed.add_field(name="Maximum charges", value=str(item["max_charges"]), inline=True)
    effects = item.get("effects") or []
    if effects:
        rendered = (
            effects_value
            if effects_value is not None
            else "\n".join("- " + _effect_one_line(effect) for effect in effects)
        )
        embed.add_field(
            name=f"Effects ({len(effects)})",
            value=rendered[:1024],
            inline=False,
        )
    footer = [f"version {item.get('version')}"]
    if item.get("schema_version"):
        footer.append(f"schema {item['schema_version']}")
    embed.set_footer(text=" · ".join(footer))
    return embed


def _effect_one_line(effect: dict[str, Any]) -> str:
    return describe_effect(effect)


def item_drop_list_entry(item: dict[str, Any]) -> tuple[str, str]:
    detail_parts = [f"ID: `{item.get('item_id', '?')}`"]
    detail_parts.append(f"Weight: {item.get('weight', '?')}")
    probability = item.get("drop_probability")
    if probability is not None:
        chance = f"{probability * 100:.2f}% per cast"
        expected = item.get("expected_casts_to_drop")
        if expected is not None:
            chance += f" (≈{expected} casts)"
        detail_parts.append(f"Chance: {chance}")
    detail_parts.append(f"XP: {item.get('xp_gain', 0)}")
    quantity = item.get("quantity")
    detail_parts.append(f"Stock: {'unlimited' if quantity is None else quantity}")
    message = item.get("message")
    if message:
        detail_parts.append(f"Message: {str(message)[:200]}")
    effects = item.get("effects") or []
    if effects:
        rendered = ", ".join(describe_effect(effect) for effect in effects)
        detail_parts.append(f"Effects: {rendered[:200]}")
    return item.get("title") or item.get("item_id", "?"), " · ".join(detail_parts)


def _format_percent(value: float, places: int = 2) -> str:
    return f"{value * 100:.{places}f}%"


def _format_duration_minutes(minutes: float) -> str:
    if minutes >= 60:
        return f"{minutes / 60:.1f} h"
    return f"{minutes:.0f} min"


def item_drop_preview_embed(
    *,
    action: str,
    location_id: str,
    preview: dict[str, Any],
    payload: dict[str, Any],
    current: dict[str, Any] | None = None,
) -> discord.Embed:
    """Shared add/edit preview for item drops (audit §5.5, §10, §14#11)."""
    embed = preview_embed(f"{action} item drop: {payload['item_id']}")
    embed.description = f"Location `{location_id}` · weight `{payload['weight']}`"

    share = preview.get("selection_weight_share")
    drop_rate = preview.get("items_drop_rate")
    if share is not None and drop_rate is not None:
        embed.add_field(
            name="Pool share",
            value=(
                f"{_format_percent(float(share))} of the pool "
                f"(location drop rate {_format_percent(float(drop_rate))})"
            ),
            inline=False,
        )

    probability = preview.get("drop_probability")
    expected = preview.get("expected_casts_to_drop")
    if probability is not None:
        chance_text = f"{_format_percent(float(probability))} per cast"
        if expected is not None:
            chance_text += f" (≈{expected} casts)"
        embed.add_field(name="Chance per cast", value=chance_text, inline=False)

    active = preview.get("expected_active_time_minutes") or {}
    expected_active = [
        (
            f"{cooldown} min: {_format_duration_minutes(float(active[cooldown]))}"
        )
        for cooldown in ("5", "7.5", "10")
        if cooldown in active
    ]
    if expected_active:
        embed.add_field(
            name="Expected active time",
            value="\n".join(expected_active),
            inline=False,
        )

    p50 = preview.get("p50")
    p90 = preview.get("p90")
    if p50 is not None and p90 is not None:
        embed.add_field(
            name="Median / 90th percentile",
            value=f"p50 {p50} casts · p90 {p90} casts",
            inline=False,
        )

    if current is not None:
        changes = _item_drop_changes(current, payload)
        if changes:
            embed.add_field(
                name="Change vs current",
                value="\n".join(changes),
                inline=False,
            )

    embed.add_field(
        name="Details",
        value=(
            f"XP: {payload.get('xp_gain', 0)}\n"
            f"Stock: {'unlimited' if payload.get('quantity') is None else payload['quantity']}\n"
            f"Message: {(payload.get('message') or '')[:200]}"
        ),
        inline=False,
    )
    return embed


def _item_drop_changes(current: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    changes = []
    for key, label in (
        ("weight", "Weight"),
        ("xp_gain", "XP"),
        ("quantity", "Stock"),
        ("message", "Message"),
    ):
        old = current.get(key)
        new = payload.get(key)
        if old == new:
            continue
        old_text = "unlimited" if key == "quantity" and old is None else str(old)
        new_text = "unlimited" if key == "quantity" and new is None else str(new)
        changes.append(f"{label}: {old_text} → {new_text}")
    return changes


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


def location_detail_embed(item: dict[str, Any]) -> discord.Embed:
    """Human-readable location card: requirements, drops summary, rewards."""
    embed = discord.Embed(
        title=item.get("location_name") or item.get("location_id") or "Location",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Location ID", value=f"`{item.get('location_id')}`", inline=True)
    if item.get("description"):
        embed.add_field(name="Description", value=str(item["description"]), inline=False)
    requirements = item.get("requirements") or {}
    if requirements:
        lines = "\n".join(f"`{key}`: {value}" for key, value in requirements.items())
        embed.add_field(name="Requirements", value=lines[:1024], inline=False)

    rewards = item.get("rewards") or item.get("rewards_data") or []
    counts: dict[str, int] = {}
    for reward in rewards:
        reward_type = str(reward.get("type") or "?")
        counts[reward_type] = counts.get(reward_type, 0) + 1
    if counts:
        embed.add_field(
            name="Rewards",
            value="\n".join(f"{reward_type}: {count}" for reward_type, count in counts.items())
            or "None",
            inline=True,
        )
    drops = item.get("item_drops") or []
    if drops:
        embed.add_field(
            name="Item drops",
            value="\n".join(
                f"`{drop.get('item_id')}` · w{drop.get('weight')}" for drop in drops[:8]
            )[:1024],
            inline=True,
        )
    if item.get("updated_at"):
        embed.set_footer(text=f"updated {item['updated_at']}")
    return embed


def player_modifiers_embed(result: dict[str, Any]) -> discord.Embed:
    """Human-readable player modifier list (no raw JSON in the primary UI)."""
    items = result.get("items") or []
    embed = discord.Embed(
        title="Player modifiers",
        description=f"Viewer: `{result.get('viewer') or result.get('username') or '?'}` · {len(items)} modifier(s)",
        color=discord.Color.blurple(),
    )
    if not items:
        embed.add_field(name="Modifiers", value="No modifiers set for this viewer.", inline=False)
        return embed
    lines = []
    for entry in items[:10]:
        stat = entry.get("stat_key") or entry.get("stat") or "?"
        op = entry.get("operation") or "?"
        value = entry.get("value")
        lines.append(f"`{stat}` **{op}** {value} · `{entry.get('source_key') or '?'}`")
    embed.add_field(name="Modifiers", value="\n".join(lines)[:1024], inline=False)
    if len(items) > 10:
        embed.set_footer(text=f"Showing 10 of {len(items)}")
    return embed


def player_inventory_embed(result: dict[str, Any], *, viewer: str) -> discord.Embed:
    """Human-readable player inventory card (no raw JSON in the primary UI).

    Each inventory row keeps the fields an administrator needs to revoke or
    diagnose (slot, title, quantity, durability, charges, inventory id) without
    dumping the full payload including definition effects and meta.
    """
    items = result.get("items") or []
    equipped_slots = result.get("equipped_slots") or {}
    equipped_values = set(equipped_slots.values())
    max_slots = result.get("max_slots")

    embed = info_embed("Player inventory")
    embed.description = (
        f"Viewer: `{viewer}`\nItems: `{len(items)}` · Slots: `{len(items)}/{max_slots or '?'}`"
    )
    if equipped_slots:
        lines = [
            f"`{slot}` → `[{inventory_slot}]`"
            for slot, inventory_slot in sorted(equipped_slots.items())
        ]
        embed.add_field(name="Equipped", value="\n".join(lines)[:1024], inline=False)

    if not items:
        embed.add_field(name="Items", value="No items.", inline=False)
        return embed

    item_lines = []
    for entry in items:
        parts = [f"[{entry.get('slot_id')}]"]
        if entry.get("slot_id") in equipped_values:
            parts.append("⭐")
        parts.append(f"**{entry.get('title') or entry.get('item_id')}** ×{entry.get('quantity')}")
        parts.append(f"({entry.get('item_type')} · {entry.get('rarity')})")
        parts.append(f"id `{entry.get('id')}`")
        if entry.get("max_durability") is not None:
            parts.append(f"dur {entry.get('current_durability')}/{entry['max_durability']}")
        if entry.get("max_charges") is not None:
            parts.append(f"charges {entry.get('current_charges')}/{entry['max_charges']}")
        item_lines.append(" ".join(parts))

    chunks = _line_chunks(item_lines)
    shown_items = 0
    for index, chunk in enumerate(chunks[:20]):
        label = "Items" if len(chunks) == 1 else f"Items ({index + 1}/{len(chunks)})"
        embed.add_field(name=label, value=chunk, inline=False)
        shown_items += chunk.count("\n") + 1
    footer = f"{len(items)} item(s)"
    if len(chunks) > 20:
        footer += f" · {len(items) - shown_items} more"
    embed.set_footer(text=footer)
    return embed


def player_overflow_embed(result: dict[str, Any], *, viewer: str) -> discord.Embed:
    """Human-readable card for items parked in durable overflow storage.

    Overflow rows are pending delivery: an administrator reviews them here and
    uses the claim command once the player has free inventory slots.
    """
    items = result.get("items") or []

    embed = warning_embed("Overflow storage")
    embed.description = f"Viewer: `{viewer}`\nParked items: `{len(items)}`"
    if not items:
        embed.add_field(name="Items", value="No items parked.", inline=False)
        return embed

    lines = []
    for entry in items:
        lines.append(
            f"`{entry.get('id')}` **{entry.get('title') or entry.get('item_id')}** "
            f"×{entry.get('quantity')} · parked <t:{_epoch(entry.get('created_at'))}:f>"
        )
    for index, chunk in enumerate(_line_chunks(lines)[:20]):
        label = "Items" if index == 0 else f"Items ({index + 1})"
        embed.add_field(name=label, value=chunk, inline=False)
    embed.set_footer(
        text="These items are held because the inventory was full. "
        "Claim them once the player has free slots."
    )
    return embed

def player_stats_explain_embed(result: dict[str, Any]) -> discord.Embed:
    """Human-readable resolved stat breakdown (no raw JSON in the primary UI).

    Only stats with at least one resolved source are rendered. Values are shown
    exactly as the backend resolved them; the per-stat contribution list names
    each source (item title, event title, or modifier reason).
    """
    embed = info_embed("Resolved player stats")
    embed.description = (
        f"Viewer: `{result.get('user_twitch_id') or '?'}`\nScope: `{result.get('scope') or '?'}`"
    )
    stats = result.get("stats") or {}
    rendered = 0
    for stat_key, entry in stats.items():
        contributions = entry.get("contributions") or []
        if not contributions:
            continue
        lines = []
        for contribution in contributions:
            source = contribution.get("label") or contribution.get("source_key") or "?"
            source_key = contribution.get("source_key")
            suffix = f" (`{source_key}`)" if source_key and source_key != source else ""
            lines.append(
                f"**{contribution.get('operation')}** {contribution.get('value')} — {source}{suffix}"
            )
        lines.append(f"→ **{entry.get('value')}**")
        embed.add_field(name=f"`{stat_key}`", value="\n".join(lines)[:1024], inline=False)
        rendered += 1
        if rendered >= 18:
            break
    if rendered == 0:
        embed.add_field(name="Stats", value="No modifiers resolved for this scope.", inline=False)

    effects = result.get("behavioral_effects") or []
    if effects:
        lines = [
            f"- **{effect.get('type')}**"
            f" ({effect.get('source_item_key') or effect.get('source_item_id') or '?'})"
            for effect in effects[:10]
        ]
        embed.add_field(
            name=f"Behavioral effects ({len(effects)})",
            value="\n".join(lines)[:1024],
            inline=False,
        )
    return embed


def reward_detail_embed(item: dict[str, Any], *, location_id: str) -> discord.Embed:
    """Human-readable reward card (no raw JSON in the primary UI).

    Base fields render as labelled fields; reward-type-specific parameters
    render as a compact ``key: value`` list, excluding already-shown fields.
    """
    title = item.get("name") or item["type"].replace("_", " ").title()
    embed = info_embed(f"Reward — {title}")
    embed.add_field(name="Reward ID", value=f"`{item.get('reward_id')}`", inline=True)
    embed.add_field(name="Type", value=item.get("type", "?"), inline=True)
    embed.add_field(name="Location", value=f"`{location_id}`", inline=True)
    embed.add_field(name="Weight", value=str(item.get("weight", "?")), inline=True)
    probability = item.get("probability")
    if probability is not None:
        embed.add_field(name="Probability", value=f"{float(probability):.2%}", inline=True)
    if item.get("xp") is not None:
        embed.add_field(name="XP", value=str(item["xp"]), inline=True)
    if item.get("message"):
        embed.add_field(name="Message", value=str(item["message"])[:1024], inline=False)
    payload_lines = [
        f"{key}: `{value}`"
        for key, value in sorted(item.items())
        if key not in _REWARD_BASE_FIELDS and value not in (None, "")
    ]
    if payload_lines:
        embed.add_field(
            name="Parameters",
            value="\n".join(payload_lines)[:1024],
            inline=False,
        )
    return embed


_REWARD_BASE_FIELDS = frozenset(
    {"reward_id", "type", "name", "weight", "xp", "message", "probability"}
)


def _line_chunks(lines: list[str], *, max_chars: int = 1024) -> list[str]:
    """Split display lines into chunks that each fit a Discord field value."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        length = len(line) + 1
        if current and current_len + length > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += length
    if current:
        chunks.append("\n".join(current))
    return chunks
