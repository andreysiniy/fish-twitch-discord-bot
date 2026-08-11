"""Typed effect builder for item wizards (no raw JSON in the primary UI).

Provides structured modal flows for each supported typed effect, plus helpers to
serialize draft effects into the backend ItemEffect payload schema.
"""

from dataclasses import dataclass, field as dc_field
from decimal import Decimal
from typing import Any, Awaitable, Callable

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


class TypedEffectModal(discord.ui.Modal):
    """Shared base for typed effect modals.

    ``on_save`` mutates the draft effects in memory. When ``on_saved`` is
    provided, the caller (effect editor) refreshes its own message after submit
    instead of sending a separate "Effect added." message (wizard spec §34).
    """

    def __init__(
        self,
        title: str,
        on_save: Callable[[dict[str, Any]], None],
        on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ):
        super().__init__(title=title)
        self.on_save = on_save
        self.on_saved = on_saved

    async def _finish(
        self,
        interaction: discord.Interaction,
        payload: dict[str, Any],
        *,
        serialize: bool = True,
    ) -> None:
        self.on_save(payload)
        if self.on_saved is not None:
            await self.on_saved(interaction)
        else:
            description = describe_effect(serialize_draft(payload) if serialize else payload)
            await interaction.response.send_message(
                f"Effect added: {description}",
                ephemeral=True,
            )


class PassiveEffectModal(TypedEffectModal):
    """Typed form for a passive stat effect (stat_add / stat_multiply)."""

    def __init__(
        self,
        effect_type: str,
        on_save: Callable[[dict[str, Any]], None],
        on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ):
        super().__init__(_label(effect_type), on_save, on_saved)
        self.effect_type = effect_type
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
        await self._finish(interaction, payload)


class GrantItemModal(TypedEffectModal):
    def __init__(
        self,
        on_save: Callable[[dict[str, Any]], None],
        on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ):
        super().__init__("Grant Item", on_save, on_saved)
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
        await self._finish(interaction, payload)


class GrantMassModal(TypedEffectModal):
    def __init__(
        self,
        on_save: Callable[[dict[str, Any]], None],
        on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ):
        super().__init__("Grant Mass", on_save, on_saved)
        self.mass = discord.ui.TextInput(label="Mass (kg)", max_length=24, required=True)
        self.add_item(self.mass)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = {"type": "grant_mass", "mass": self.mass.value.strip()}
        await self._finish(interaction, payload)


class RerollRewardModal(TypedEffectModal):
    def __init__(
        self,
        on_save: Callable[[dict[str, Any]], None],
        on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ):
        super().__init__("Reroll Reward", on_save, on_saved)
        self.targets = discord.ui.TextInput(
            label="Target actions (comma separated)",
            placeholder="nothing, negative_mass, negative_percentage",
            max_length=120,
            required=True,
        )
        self.max_rerolls = discord.ui.TextInput(
            label="Max rerolls", max_length=2, default="1", required=True
        )
        self.durability_cost = discord.ui.TextInput(
            label="Durability cost", max_length=4, default="0", required=True
        )
        for item in (self.targets, self.max_rerolls, self.durability_cost):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = {
            "type": "reroll_reward",
            "trigger": "after_reward_roll",
            "target_action_types": [
                part.strip() for part in self.targets.value.split(",") if part.strip()
            ],
            "max_rerolls": int(self.max_rerolls.value.strip() or "1"),
            "durability_cost": int(self.durability_cost.value.strip() or "0"),
        }
        await self._finish(interaction, payload)


class BlockActionModal(TypedEffectModal):
    def __init__(
        self,
        on_save: Callable[[dict[str, Any]], None],
        on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ):
        super().__init__("Block Action", on_save, on_saved)
        self.targets = discord.ui.TextInput(
            label="Target actions (comma separated)",
            placeholder="nothing, negative_mass",
            max_length=120,
            required=True,
        )
        self.trigger = discord.ui.TextInput(
            label="Trigger",
            placeholder="after_reward_roll",
            default="after_reward_roll",
            max_length=30,
            required=True,
        )
        self.chance = discord.ui.TextInput(
            label="Chance (0..1)", default="1", max_length=8, required=True
        )
        self.durability_cost = discord.ui.TextInput(
            label="Durability cost", max_length=4, default="0", required=True
        )
        for item in (self.targets, self.trigger, self.chance, self.durability_cost):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = {
            "type": "block_action",
            "trigger": self.trigger.value.strip() or "after_reward_roll",
            "target_action_types": [
                part.strip() for part in self.targets.value.split(",") if part.strip()
            ],
            "chance": self.chance.value.strip() or "1",
            "durability_cost": int(self.durability_cost.value.strip() or "0"),
        }
        await self._finish(interaction, payload)


class RobberyCounterModal(TypedEffectModal):
    def __init__(
        self,
        on_save: Callable[[dict[str, Any]], None],
        on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ):
        super().__init__("Robbery Counter", on_save, on_saved)
        self.trigger = discord.ui.TextInput(
            label="Trigger", default="on_robbery_attempt", max_length=30, required=True
        )
        self.chance = discord.ui.TextInput(
            label="Chance (0..1)", default="1", max_length=8, required=True
        )
        self.action_type = discord.ui.TextInput(
            label="Counter action",
            placeholder="timeout",
            default="timeout",
            max_length=20,
            required=True,
        )
        self.duration = discord.ui.TextInput(
            label="Timeout duration (seconds)", default="60", max_length=9, required=True
        )
        for item in (self.trigger, self.chance, self.action_type, self.duration):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        action_type = (self.action_type.value.strip() or "timeout").lower()
        if action_type not in ("timeout", "add_mass"):
            await interaction.response.send_message(
                "Counter action must be `timeout` or `add_mass`.", ephemeral=True
            )
            return
        action = (
            {"type": "timeout", "duration_seconds": int(self.duration.value.strip() or "60")}
            if action_type == "timeout"
            else {"type": "add_mass", "mass": self.duration.value.strip() or "0"}
        )
        payload = {
            "type": "robbery_counter",
            "trigger": self.trigger.value.strip() or "on_robbery_attempt",
            "chance": self.chance.value.strip() or "1",
            "action": action,
            "durability_cost": 1,
        }
        await self._finish(interaction, payload)


class AbsorbRobberyModal(TypedEffectModal):
    def __init__(
        self,
        on_save: Callable[[dict[str, Any]], None],
        on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ):
        super().__init__("Absorb Robbery", on_save, on_saved)
        self.chance = discord.ui.TextInput(
            label="Chance (0..1)", default="1", max_length=8, required=True
        )
        self.attacker_delta = discord.ui.TextInput(
            label="Attacker mass delta", default="0", max_length=24, required=True
        )
        self.durability_cost = discord.ui.TextInput(
            label="Durability cost", max_length=4, default="1", required=True
        )
        for item in (self.chance, self.attacker_delta, self.durability_cost):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = {
            "type": "absorb_robbery",
            "trigger": "on_robbery_attempt",
            "chance": self.chance.value.strip() or "1",
            "attacker_mass_delta": self.attacker_delta.value.strip() or "0",
            "durability_cost": int(self.durability_cost.value.strip() or "1"),
        }
        await self._finish(interaction, payload)


class MassFloorModal(TypedEffectModal):
    def __init__(
        self,
        on_save: Callable[[dict[str, Any]], None],
        on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ):
        super().__init__("Mass Floor", on_save, on_saved)
        self.protected_mass = discord.ui.TextInput(
            label="Protected mass", max_length=24, required=True
        )
        self.scopes = discord.ui.TextInput(
            label="Scopes (comma separated)",
            placeholder="robbery, negative_rewards, roulette",
            max_length=80,
            required=True,
        )
        self.add_item(self.protected_mass)
        self.add_item(self.scopes)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = {
            "type": "mass_floor",
            "protected_mass": self.protected_mass.value.strip(),
            "scopes": [
                part.strip()
                for part in self.scopes.value.split(",")
                if part.strip() in ("robbery", "negative_rewards", "roulette")
            ],
        }
        if not payload["scopes"]:
            await interaction.response.send_message(
                "Scopes must be from: robbery, negative_rewards, roulette.",
                ephemeral=True,
            )
            return
        await self._finish(interaction, payload)


class ApplyTimeoutModal(TypedEffectModal):
    def __init__(
        self,
        on_save: Callable[[dict[str, Any]], None],
        on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ):
        super().__init__("Apply Timeout", on_save, on_saved)
        self.duration = discord.ui.TextInput(
            label="Duration (seconds)", max_length=9, required=True
        )
        self.reason = discord.ui.TextInput(
            label="Reason", max_length=200, default="Item effect", required=True
        )
        self.add_item(self.duration)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = {
            "type": "apply_timeout",
            "duration_seconds": int(self.duration.value.strip()),
            "reason": self.reason.value.strip() or "Item effect",
        }
        await self._finish(interaction, payload)


class LootTableRollModal(TypedEffectModal):
    def __init__(
        self,
        on_save: Callable[[dict[str, Any]], None],
        on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ):
        super().__init__("Loot Table Roll", on_save, on_saved)
        self.table_id = discord.ui.TextInput(label="Loot table ID", max_length=120, required=True)
        self.rolls = discord.ui.TextInput(label="Rolls", default="1", max_length=2, required=True)
        self.add_item(self.table_id)
        self.add_item(self.rolls)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = {
            "type": "loot_table_roll",
            "loot_table_id": self.table_id.value.strip(),
            "rolls": int(self.rolls.value.strip() or "1"),
        }
        await self._finish(interaction, payload)


class ConsumeChargeModal(TypedEffectModal):
    def __init__(
        self,
        on_save: Callable[[dict[str, Any]], None],
        on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ):
        super().__init__("Consume Charge", on_save, on_saved)
        self.trigger = discord.ui.TextInput(
            label="Trigger",
            placeholder="on_use",
            default="on_use",
            max_length=30,
            required=True,
        )
        self.amount = discord.ui.TextInput(label="Amount", default="1", max_length=4, required=True)
        self.add_item(self.trigger)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = {
            "type": "consume_charge",
            "trigger": self.trigger.value.strip() or "on_use",
            "amount": int(self.amount.value.strip() or "1"),
        }
        await self._finish(interaction, payload)


def modal_for_effect(
    effect_type: str,
    on_save: Callable[[dict[str, Any]], None],
    on_saved: Callable[[discord.Interaction], Awaitable[None]] | None = None,
):
    """Return the typed modal for an effect type (never None)."""
    if effect_type in ("stat_add", "stat_multiply"):
        return PassiveEffectModal(effect_type, on_save, on_saved)
    if effect_type == "grant_item":
        return GrantItemModal(on_save, on_saved)
    if effect_type == "grant_mass":
        return GrantMassModal(on_save, on_saved)
    if effect_type == "reroll_reward":
        return RerollRewardModal(on_save, on_saved)
    if effect_type == "block_action":
        return BlockActionModal(on_save, on_saved)
    if effect_type == "robbery_counter":
        return RobberyCounterModal(on_save, on_saved)
    if effect_type == "absorb_robbery":
        return AbsorbRobberyModal(on_save, on_saved)
    if effect_type == "mass_floor":
        return MassFloorModal(on_save, on_saved)
    if effect_type == "apply_timeout":
        return ApplyTimeoutModal(on_save, on_saved)
    if effect_type == "loot_table_roll":
        return LootTableRollModal(on_save, on_saved)
    if effect_type == "consume_charge":
        return ConsumeChargeModal(on_save, on_saved)
    return PassiveEffectModal("stat_add", on_save, on_saved)
