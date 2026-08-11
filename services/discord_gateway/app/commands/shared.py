"""Shared command helpers for the /fish domain modules.

Kept out of the per-domain modules so the audit rule "commands live in domain
modules" holds while the shared mutation/confirmation/JSON plumbing stays in
one place.
"""

import io
import json
from datetime import datetime
from typing import Any

import discord
from discord import app_commands

from app.api.errors import EngineError, localize_error
from app.interactions.confirms import ConfirmView
from app.interactions.sessions import WizardSessionStore

__all__ = [
    "SECTION_CHOICES",
    "REWARD_CHOICES",
    "ITEM_TYPE_CHOICES",
    "RARITY_CHOICES",
    "EQUIPMENT_SLOT_CHOICES",
    "BREAK_POLICY_CHOICES",
    "MODIFIER_OPERATION_CHOICES",
    "MODIFIER_SCOPE_CHOICES",
    "STAT_KEY_CHOICES",
]


SECTION_CHOICES = [
    app_commands.Choice(name=value.title(), value=value)
    for value in ("xp", "economy", "robbery", "cooldown")
]
REWARD_CHOICES = [
    app_commands.Choice(name=value.replace("_", " ").title(), value=value)
    for value in ("fish", "timeout", "robbery", "russian_roulette", "dupe", "nothing")
]
ITEM_TYPE_CHOICES = [
    app_commands.Choice(name=value.title(), value=value)
    for value in (
        "equipment",
        "consumable",
        "lootbox",
        "material",
        "quest",
        "currency",
        "collectible",
    )
]
RARITY_CHOICES = [
    app_commands.Choice(name=value.title(), value=value)
    for value in ("common", "rare", "epic", "legendary")
]
EQUIPMENT_SLOT_CHOICES = [
    app_commands.Choice(name=value.replace("_", " ").title(), value=value)
    for value in ("rod", "bait", "defense", "storage", "charm_1", "charm_2")
]
BREAK_POLICY_CHOICES = [
    app_commands.Choice(name=value.replace("_", " ").title(), value=value)
    for value in ("indestructible", "retain_broken", "unequip_broken", "destroy_at_zero")
]
MODIFIER_OPERATION_CHOICES = [
    app_commands.Choice(name=value.title(), value=value)
    for value in ("add", "multiply", "override", "min", "max")
]
MODIFIER_SCOPE_CHOICES = [
    app_commands.Choice(name=value.title(), value=value)
    for value in ("fishing", "robbery", "economy", "inventory", "all")
]
STAT_KEY_CHOICES = [
    app_commands.Choice(name=value.replace("_", " ").title(), value=value)
    for value in (
        "fish_luck_change_ratio",
        "positive_fish_reward_change_ratio",
        "negative_fish_reward_change_ratio",
        "xp_gain_change_ratio",
        "points_flat_bonus",
        "item_drop_chance_add",
        "item_rarity_luck_pct",
        "cooldown_change_ratio",
        "empty_catch_reroll_chance_pct",
        "robbery_protection_pct",
        "robbery_evasion_pct",
        "protected_mass_flat",
        "robbery_counter_chance_pct",
        "robbery_attack_chance_add",
        "robbery_amount_bonus_pct",
        "inventory_slots_add",
        "sell_rate_bonus_pct",
        "buy_discount_pct",
    )
]


async def _deferred(interaction: discord.Interaction, operation) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        await operation()
    except (EngineError, ValueError) as error:
        await _send_error(interaction, error)


async def _simple_mutation(interaction, operation, success: str) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        await operation()
        await interaction.followup.send(success, ephemeral=True)
    except (EngineError, ValueError) as error:
        await _send_error(interaction, error)


async def _mutation_response(interaction, operation, success: str) -> None:
    if not interaction.response.is_done():
        if interaction.type is discord.InteractionType.component:
            # Confirm buttons may only ack with DEFERRED_MESSAGE_UPDATE (type 6);
            # discord.py maps thinking=True to DEFERRED_CHANNEL_MESSAGE (type 5),
            # which Discord rejects for component interactions, leaving the click
            # unanswered and timing out after 3 seconds.
            await interaction.response.defer()
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        await operation()
        await interaction.edit_original_response(content=success, embed=None, view=None)
    except (EngineError, ValueError) as error:
        await interaction.edit_original_response(content=_error_text(error), embed=None, view=None)


async def _confirmation(interaction, prompt, operation, success, *, danger=False) -> None:
    async def confirm(confirmed: discord.Interaction) -> None:
        await _mutation_response(confirmed, lambda: operation(confirmed), success)

    await interaction.response.send_message(
        prompt,
        view=ConfirmView(interaction.user.id, confirm, danger=danger),
        ephemeral=True,
    )


async def _json_confirmation(
    interaction,
    title: str,
    payload: dict[str, Any],
    operation,
    success: str,
) -> None:
    async def confirm(confirmed: discord.Interaction) -> None:
        await _mutation_response(confirmed, lambda: operation(confirmed), success)

    embed = _json_embed(title, payload)
    view = ConfirmView(interaction.user.id, confirm)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=embed, view=view)
    else:
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def _send_error(interaction: discord.Interaction, error: Exception) -> None:
    content = _error_text(error)
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


def _error_text(error: Exception) -> str:
    if isinstance(error, EngineError):
        return localize_error(error)
    return str(error) or "The operation could not be completed."


def _json_embed(title: str, item: dict[str, Any]) -> discord.Embed:
    """Embed for JSON payloads; never silently truncates (callers attach files)."""
    rendered = json.dumps(item, ensure_ascii=False, indent=2, default=str)
    if len(rendered) > 3900:
        return discord.Embed(
            title=title,
            description="(JSON too large for the embed — full JSON attached as a file)",
            color=discord.Color.blurple(),
        )
    return discord.Embed(
        title=title, description=f"```json\n{rendered}\n```", color=discord.Color.blurple()
    )


def _player_modifier_preview_embed(
    *,
    user_twitch_id: str,
    scope: str,
    stat_key: str,
    op_label: str,
    value: str,
    current_resolved: str,
    existing_source_count: int,
    source_key: str,
    reason: str,
    expires_at: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Player modifier preview — {user_twitch_id}",
        description=(
            f"Scope: `{scope}` · Stat: `{stat_key}`\nOperation: **{op_label}** with value `{value}`"
        ),
        color=discord.Color.orange(),
    )
    embed.add_field(
        name="Current resolved value",
        value=current_resolved,
        inline=True,
    )
    embed.add_field(
        name="Existing sources",
        value=str(existing_source_count),
        inline=True,
    )
    if expires_at:
        embed.add_field(
            name="Expires",
            value=f"<t:{_epoch_from_iso(expires_at)}:f>",
            inline=True,
        )
    embed.add_field(
        name="Source",
        value=f"{source_key}\n{reason}",
        inline=False,
    )
    if op_label.lower() == "override" or existing_source_count:
        embed.add_field(
            name="⚠️ Warning",
            value=(
                "This targets a stat that already has modifiers. "
                "Override replaces the resolved value; add/multiply stacks "
                "on top of the current total."
            ),
            inline=False,
        )
    return embed


async def _send_json_embed(
    interaction: discord.Interaction,
    title: str,
    item: dict[str, Any],
) -> None:
    """Never truncates JSON silently: oversized payloads are attached as files."""
    rendered = json.dumps(item, ensure_ascii=False, indent=2, default=str)
    embed = _json_embed(title, item)
    kwargs: dict[str, Any] = {"ephemeral": True}
    if len(rendered) > 3900:
        embed.description = f"```json\n{rendered[:900]}\n```\n(full JSON attached as a file)"
        kwargs["file"] = discord.File(io.StringIO(rendered), filename=f"{title.lower()}.json")
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, **kwargs)
    else:
        await interaction.response.send_message(embed=embed, **kwargs)


async def _session(
    sessions: WizardSessionStore,
    interaction: discord.Interaction,
    flow_id: str,
) -> dict[str, Any]:
    state = await sessions.get(interaction.user.id, flow_id)
    if state is None:
        raise ValueError("This form expired. Run the command again.")
    return state


async def _require_owner(api, interaction: discord.Interaction) -> None:
    """Owner gate for raw/advanced commands (wizard spec §56).

    The owner is the Twitch account that owns the bound channel — the same rule
    the backend applies in ``_authorize`` (``link.twitch_user_id ==
    channel.twitch_id``). The backend remains authoritative for the mutation
    itself; this is the UI-level policy that keeps raw JSON owner-only.
    """
    status = await api.status(interaction)
    twitch = status.get("twitch") or {}
    binding = status.get("binding") or {}
    if not twitch.get("id") or not binding.get("channel_twitch_id"):
        raise EngineError(
            403, "TWITCH_OWNER_REQUIRED", "Only the Twitch channel owner can use this."
        )
    if str(twitch["id"]) != str(binding["channel_twitch_id"]):
        raise EngineError(
            403, "TWITCH_OWNER_REQUIRED", "Only the Twitch channel owner can use this."
        )


def _parse_effects(raw: str | None) -> list[dict[str, Any]]:
    if raw is None or not raw.strip():
        return []
    try:
        effects = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"Effects must be valid JSON: {error.msg}") from error
    if not isinstance(effects, list) or not all(isinstance(item, dict) for item in effects):
        raise ValueError("Effects must be a JSON array of objects")
    return effects


def _item_payload(
    *,
    item_id: str,
    title: str,
    item_type: str,
    rarity: str,
    equipment_slot: str | None,
    stack_size: int,
    max_durability: int | None,
    max_charges: int | None = None,
    break_policy: str,
    effects: list[dict[str, Any]],
    description: str | None,
    schema_version: int | None = None,
    image_url: str | None = None,
    nominal_value: str | None = None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    if item_type == "equipment" and not equipment_slot:
        raise ValueError("Equipment slot is required for equipment")
    if item_type != "equipment" and equipment_slot:
        raise ValueError("Equipment slot is only available for equipment")
    if item_type == "equipment" and stack_size != 1:
        raise ValueError("Equipment must use stack size 1")
    if break_policy != "indestructible" and max_durability is None:
        raise ValueError("Maximum durability is required for breakable items")
    if item_type != "consumable" and max_charges is not None:
        raise ValueError("Maximum charges are only available for consumables")
    if max_charges is not None and stack_size != 1:
        raise ValueError("Charge-based consumables must use stack size 1")
    payload = {
        "item_id": item_id.strip().lower(),
        "title": title.strip(),
        "description": description.strip() if description else None,
        "item_type": item_type,
        "equipment_slot": equipment_slot,
        "rarity": rarity,
        "stack_size": stack_size,
        "max_durability": max_durability,
        "max_charges": max_charges,
        "break_policy": break_policy,
        "schema_version": schema_version if schema_version is not None else 1,
        "effects": effects,
        "image_url": image_url,
        "nominal_value": nominal_value,
    }
    if expected_version is not None:
        payload["expected_version"] = expected_version
    return payload


def _epoch_from_iso(value: str) -> int:
    """Unix timestamp for a backend ISO datetime (used for Discord <t:> tags)."""
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0
