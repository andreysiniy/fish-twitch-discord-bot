import json
from typing import Any

import discord

from app.interactions.confirms import ConfirmView
from app.interactions.reward_payloads import build_reward_payload
from app.presentation.embeds import diff_embed
from app.presentation.formatting import parse_decimal


class ConfigModal(discord.ui.Modal):
    def __init__(
        self,
        section: str,
        current: dict[str, Any],
        schema: dict[str, Any],
        on_save,
    ):
        super().__init__(title=f"Settings: {section}")
        self.section = section
        self.current = current
        self.on_save = on_save
        self.inputs: dict[str, discord.ui.TextInput] = {}
        self.field_schemas = schema["sections"][section]["fields"]
        for field, field_schema in self.field_schemas.items():
            item = discord.ui.TextInput(
                label=field,
                default=str(current[field]),
                placeholder=_schema_constraint(field_schema),
                max_length=32,
            )
            self.inputs[field] = item
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        changes = {}
        try:
            for key, item in self.inputs.items():
                value = item.value.strip()
                changes[key] = (
                    int(value)
                    if self.field_schemas[key].get("type") == "integer"
                    else parse_decimal(value)
                )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        preview = {**self.current, **changes}

        async def confirm(confirm_interaction):
            await self.on_save(confirm_interaction, changes)

        await interaction.response.send_message(
            embed=diff_embed("Change preview", self.current, preview),
            view=ConfirmView(interaction.user.id, confirm),
            ephemeral=True,
        )


class LocationModal(discord.ui.Modal):
    location_id = discord.ui.TextInput(label="ID", placeholder="river", max_length=32)
    location_name = discord.ui.TextInput(label="Name", max_length=80)
    items_drop_rate = discord.ui.TextInput(label="Item drop chance 0..1", default="0.1")
    level = discord.ui.TextInput(label="Minimum level", default="0", required=False)

    def __init__(self, on_save, defaults: dict[str, Any] | None = None):
        defaults = defaults or {}
        super().__init__(title="Edit location" if defaults else "New location")
        self.on_save = on_save
        self.expected_version = defaults.get("version")
        self.location_id.default = str(defaults.get("location_id") or "")
        self.location_id.disabled = bool(defaults)
        self.location_name.default = str(defaults.get("location_name") or "")
        self.items_drop_rate.default = str(defaults.get("items_drop_rate", "0.1"))
        self.level.default = str((defaults.get("requirements") or {}).get("level") or "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            payload = {
                "location_id": self.location_id.value.strip(),
                "location_name": self.location_name.value.strip(),
                "items_drop_rate": parse_decimal(self.items_drop_rate.value),
                "requirements": (
                    {"level": int(self.level.value)} if self.level.value.strip() else {}
                ),
            }
            if self.expected_version is not None:
                payload["expected_version"] = self.expected_version
                payload.pop("location_id")
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        async def confirm(confirm_interaction: discord.Interaction) -> None:
            await self.on_save(confirm_interaction, payload)

        rendered = json.dumps(payload, ensure_ascii=True, indent=2)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Location preview",
                description=f"```json\n{rendered[:3800]}\n```",
                color=discord.Color.orange(),
            ),
            view=ConfirmView(interaction.user.id, confirm),
            ephemeral=True,
        )


class RewardModal(discord.ui.Modal):
    name = discord.ui.TextInput(label="Name", required=False, max_length=80)
    weight = discord.ui.TextInput(label="Weight", default="100")
    xp = discord.ui.TextInput(label="XP", default="0")
    message = discord.ui.TextInput(label="Message", required=False, max_length=300)
    parameters = discord.ui.TextInput(
        label="Parameters key=value;...",
        required=False,
        max_length=300,
        placeholder="fish: range=0.1,5 | timeout: duration=10m;reason=...",
    )

    def __init__(self, reward_type: str, on_save, defaults: dict[str, Any] | None = None):
        super().__init__(title=f"Reward: {reward_type}")
        self.reward_type = reward_type
        self.on_save = on_save
        defaults = defaults or {}
        self.name.default = str(defaults.get("name") or "")
        self.weight.default = str(defaults.get("weight", 100))
        self.xp.default = str(defaults.get("xp", 0))
        self.message.default = str(defaults.get("message") or "")
        self.parameters.default = _reward_parameters(defaults)
        if reward_type == "russian_roulette":
            self.parameters.placeholder = (
                "bullets=1;chambers=6;reward=add_mass:2;penalty=timeout:1m"
            )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            payload = build_reward_payload(
                self.reward_type,
                self.name.value,
                self.weight.value,
                self.xp.value,
                self.message.value,
                self.parameters.value,
            )
        except (TypeError, ValueError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        async def confirm(confirm_interaction: discord.Interaction) -> None:
            await self.on_save(confirm_interaction, payload)

        rendered = json.dumps(payload, ensure_ascii=True, indent=2)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Reward preview",
                description=f"```json\n{rendered[:3800]}\n```",
                color=discord.Color.orange(),
            ),
            view=ConfirmView(interaction.user.id, confirm),
            ephemeral=True,
        )


class EventModal(discord.ui.Modal):
    title_input = discord.ui.TextInput(label="Name", max_length=120)
    options = discord.ui.TextInput(
        label="Options key=value;...",
        required=False,
        max_length=100,
        placeholder="location=lake;bonus_mass=0.15",
    )
    luck_mult = discord.ui.TextInput(label="Luck multiplier", default="1")
    xp_mult = discord.ui.TextInput(label="XP multiplier", default="1")
    cooldown_reduction = discord.ui.TextInput(label="Cooldown reduction 0..0.95", default="0")

    def __init__(self, on_save, defaults: dict[str, Any] | None = None):
        defaults = defaults or {}
        super().__init__(title="Edit event" if defaults else "New event")
        self.on_save = on_save
        self.expected_version = defaults.get("version")
        modifiers = defaults.get("modifiers") or {}
        self.title_input.default = str(defaults.get("event_title") or "")
        option_values = []
        if defaults.get("override_loot_pool"):
            option_values.append(f"location={defaults['override_loot_pool']}")
        option_values.append(f"bonus_mass={modifiers.get('bonus_mass', '0')}")
        self.options.default = ";".join(option_values)
        self.luck_mult.default = str(modifiers.get("luck_mult", "1"))
        self.xp_mult.default = str(modifiers.get("xp_mult", "1"))
        self.cooldown_reduction.default = str(modifiers.get("cd_reduction", "0"))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            options = _parse_options(self.options.value)
            payload = {
                "event_title": self.title_input.value,
                "override_loot_pool": options.get("location") or None,
                "modifiers": {
                    "luck_mult": parse_decimal(self.luck_mult.value),
                    "xp_mult": parse_decimal(self.xp_mult.value),
                    "cd_reduction": parse_decimal(self.cooldown_reduction.value),
                    "bonus_mass": parse_decimal(options.get("bonus_mass", "0")),
                },
            }
            if self.expected_version is not None:
                payload["expected_version"] = self.expected_version
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await self.on_save(interaction, payload)


def _reward_parameters(reward: dict[str, Any]) -> str:
    reward_type = reward.get("type")
    values: list[str] = []
    if reward_type == "fish":
        if reward.get("fixed_mass") is not None:
            values.append(f"fixed={reward['fixed_mass']}")
        elif reward.get("percentage") is not None:
            values.append(f"percentage={reward['percentage']}")
        elif reward.get("min_mass") is not None:
            values.append(f"range={reward['min_mass']},{reward['max_mass']}")
    elif reward_type == "timeout":
        values.extend(
            [f"duration={reward.get('duration', '')}", f"reason={reward.get('reason', '')}"]
        )
    elif reward_type == "robbery":
        key = "percentage" if reward.get("percentage") is not None else "mass"
        values.extend([f"{key}={reward.get(key, '')}", f"range={reward.get('range', 3)}"])
    elif reward_type == "russian_roulette":
        values.extend(
            [
                f"bullets={reward.get('bullets', 1)}",
                f"chambers={reward.get('chambers', 6)}",
                f"safe={reward.get('safe_message', '')}",
                f"shot={reward.get('shot_message', '')}",
            ]
        )
        if reward.get("reward"):
            values.append(f"reward={_format_outcome(reward['reward'])}")
        if reward.get("penalty"):
            values.append(f"penalty={_format_outcome(reward['penalty'])}")
    return ";".join(values)


def _format_outcome(outcome: dict[str, Any]) -> str:
    outcome_type = outcome["type"]
    if outcome_type == "add_mass":
        return f"{outcome_type}:{outcome['mass']}"
    if outcome_type == "add_percentage_mass":
        return f"{outcome_type}:{outcome['percentage']}"
    return f"timeout:{outcome['duration']},{outcome.get('reason', '')}"


def _schema_constraint(field_schema: dict[str, Any]) -> str | None:
    candidates = [field_schema, *field_schema.get("anyOf", [])]
    numeric = next(
        (candidate for candidate in candidates if "minimum" in candidate or "maximum" in candidate),
        None,
    )
    if not numeric:
        return None
    return f"Range: {numeric.get('minimum', '-inf')} to {numeric.get('maximum', 'inf')}"


def _parse_options(value: str) -> dict[str, str]:
    options = {}
    for chunk in value.split(";"):
        if not chunk.strip():
            continue
        key, separator, raw_value = chunk.partition("=")
        if not separator or not key.strip() or not raw_value.strip():
            raise ValueError("Use key=value;key=value for event options")
        options[key.strip().lower()] = raw_value.strip()
    unknown = set(options) - {"location", "bonus_mass"}
    if unknown:
        raise ValueError(f"Unknown event option: {min(unknown)}")
    return options
