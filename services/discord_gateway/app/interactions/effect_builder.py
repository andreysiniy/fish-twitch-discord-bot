"""Typed effect builder for item wizards (no raw JSON in the primary UI).

Provides structured modal flows for each supported typed effect, plus helpers to
serialize draft effects into the backend ItemEffect payload schema.
"""

from dataclasses import dataclass, field as dc_field
from decimal import Decimal
from typing import Any, Callable

import discord

# Effect types the builder can produce, grouped by category.
PASSIVE_EFFECTS: list[str] = ["stat_add", "stat_multiply"]
TRIGGERED_EFFECTS: list[str] = [
    "reroll_reward",
    "block_action",
    "robbery_counter",
    "absorb_robbery",
    "mass_floor",
    "grant_item",
    "grant_mass",
    "apply_timeout",
    "loot_table_roll",
    "consume_charge",
]


def _label(effect: str) -> str:
    return effect.replace("_", " ").title()


EFFECT_SELECT_OPTIONS = [
    discord.SelectOption(label=_label(effect) or effect, value=effect)
    for effect in PASSIVE_EFFECTS + TRIGGERED_EFFECTS
]


@dataclass
class DraftEffect:
    """Editor state for one draft effect."""

    payload: dict[str, Any] = dc_field(default_factory=dict)


def effect_to_choice(effect: dict[str, Any]) -> str:
    return str(effect.get("type") or "stat_add")


def serialize_draft(effect: dict[str, Any]) -> dict[str, Any]:
    """Normalize a typed draft effect into the backend payload shape."""
    payload = dict(effect)
    effect_type = str(payload.get("type") or "")
    if effect_type in ("stat_add", "stat_multiply"):
        payload["trigger"] = "passive"
        payload["value"] = str(parse_decimal_safe(payload.get("value", 0)))
    return payload


def parse_decimal_safe(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def describe_effect(effect: dict[str, Any]) -> str:
    """Human-readable one-line description of a draft effect."""
    effect_type = str(effect.get("type") or "?")
    if effect_type == "stat_add":
        return f"{_label(effect_type)}: {effect.get('stat')} {_percent(effect.get('value'))}"
    if effect_type == "stat_multiply":
        return f"Stat multiplier: {effect.get('stat')} ×{effect.get('value')}"
    if effect_type == "grant_item":
        return f"Grant item: {effect.get('item_id')} ×{effect.get('quantity', 1)}"
    if effect_type == "grant_mass":
        return f"Grant mass: {effect.get('mass')} kg"
    if effect_type == "apply_timeout":
        return f"Timeout: {effect.get('duration_seconds')}s"
    if effect_type == "reroll_reward":
        return f"Reroll reward: {effect.get('target_action_types', [])}"
    if effect_type == "block_action":
        return f"Block action: {effect.get('target_action_types', [])}"
    if effect_type == "robbery_counter":
        return "Robbery counter"
    if effect_type == "absorb_robbery":
        return "Absorb robbery"
    if effect_type == "mass_floor":
        return f"Mass floor: {effect.get('protected_mass')}"
    if effect_type == "loot_table_roll":
        return f"Loot roll: {effect.get('loot_table_id')} ×{effect.get('rolls', 1)}"
    if effect_type == "consume_charge":
        return f"Consume charge: {effect.get('amount', 1)} ({effect.get('trigger')})"
    return effect_type


def _percent(value: Any) -> str:
    try:
        return f"{Decimal(str(value)) * 100:.0f}%"
    except Exception:
        return f"{value}"


class PassiveEffectModal(discord.ui.Modal):
    """Typed form for a passive stat effect (stat_add / stat_multiply)."""

    def __init__(self, effect_type: str, on_save: Callable[[dict[str, Any]], None]):
        super().__init__(title=_label(effect_type))
        self.effect_type = effect_type
        self.on_save = on_save
        self.stat = discord.ui.TextInput(
            label="Stat key",
            placeholder="fish_luck_change_ratio / positive_fish_reward_change_ratio ...",
            max_length=60,
            required=True,
        )
        self.value = discord.ui.TextInput(
            label="Value (ratio; 0.10 = +10%)",
            max_length=24,
            required=True,
        )
        self.add_item(self.stat)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = {
            "type": self.effect_type,
            "stat": self.stat.value.strip(),
            "value": self.value.value.strip(),
        }
        self.on_save(payload)
        await interaction.response.send_message(
            f"Effect added: {describe_effect(serialize_draft(payload))}",
            ephemeral=True,
        )


class GrantItemModal(discord.ui.Modal):
    def __init__(self, on_save: Callable[[dict[str, Any]], None]):
        super().__init__(title="Grant Item")
        self.on_save = on_save
        self.item_id = discord.ui.TextInput(label="Item ID", max_length=120, required=True)
        self.quantity = discord.ui.TextInput(
            label="Quantity", max_length=9, default="1", required=True
        )
        self.add_item(self.item_id)
        self.add_item(self.quantity)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = {
            "type": "grant_item",
            "item_id": self.item_id.value.strip(),
            "quantity": int(self.quantity.value.strip() or "1"),
        }
        self.on_save(payload)
        await interaction.response.send_message(
            f"Effect added: {describe_effect(payload)}", ephemeral=True
        )


class GrantMassModal(discord.ui.Modal):
    def __init__(self, on_save: Callable[[dict[str, Any]], None]):
        super().__init__(title="Grant Mass")
        self.on_save = on_save
        self.mass = discord.ui.TextInput(label="Mass (kg)", max_length=24, required=True)
        self.add_item(self.mass)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = {"type": "grant_mass", "mass": self.mass.value.strip()}
        self.on_save(payload)
        await interaction.response.send_message(
            f"Effect added: {describe_effect(payload)}", ephemeral=True
        )


def modal_for_effect(effect_type: str, on_save: Callable[[dict[str, Any]], None]):
    """Return the typed modal for an effect type."""
    if effect_type in ("stat_add", "stat_multiply"):
        return PassiveEffectModal(effect_type, on_save)
    if effect_type == "grant_item":
        return GrantItemModal(on_save)
    if effect_type == "grant_mass":
        return GrantMassModal(on_save)
    return None
