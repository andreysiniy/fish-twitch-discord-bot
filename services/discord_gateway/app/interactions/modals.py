import io
import json
from decimal import Decimal
from typing import Any

import discord

from app.api.errors import EngineError, localize_error
from app.domain.percent_helpers import ratio_to_percent
from app.interactions.confirms import ConfirmView
from app.interactions.launchers import ModalLauncherView
from app.interactions.reward_payloads import (
    build_reward_base_payload,
    build_roulette_outcome,
    complete_reward_payload,
)
from app.presentation.embeds import diff_embed, item_drop_preview_embed
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


class MessageTemplateModal(discord.ui.Modal):
    def __init__(self, item: dict[str, Any], on_save):
        super().__init__(title=f"Message: {item['message_key']}"[:45])
        self.item = item
        self.on_save = on_save
        allowed = ", ".join(f"{{{placeholder['name']}}}" for placeholder in item["placeholders"])
        self.allowed_placeholders = discord.ui.TextInput(
            label="Allowed placeholders",
            default=allowed or "None",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
        )
        self.allowed_placeholders.disabled = True
        self.template = discord.ui.TextInput(
            label="Message template (empty resets)",
            default=item["effective_message"],
            placeholder="Enter a custom English message or clear to reset",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
        )
        self.add_item(self.allowed_placeholders)
        self.add_item(self.template)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        template = self.template.value.strip() or None
        after = template or self.item["default_message"]

        async def confirm(confirm_interaction: discord.Interaction) -> None:
            await self.on_save(confirm_interaction, template)

        await interaction.response.send_message(
            embed=diff_embed(
                "Message change preview",
                {"template": self.item["effective_message"]},
                {"template": after},
            ),
            view=ConfirmView(interaction.user.id, confirm),
            ephemeral=True,
        )


class LocationModal(discord.ui.Modal):
    def __init__(self, on_save, defaults: dict[str, Any] | None = None):
        defaults = defaults or {}
        super().__init__(title="Edit location" if defaults else "New location")
        self.on_save = on_save
        self.expected_version = defaults.get("version")
        self.location_id = discord.ui.TextInput(
            label="ID",
            default=str(defaults.get("location_id") or ""),
            placeholder="Lowercase ID, for example: river",
            max_length=32,
        )
        self.location_id.disabled = bool(defaults)
        self.location_name = discord.ui.TextInput(
            label="Name",
            default=str(defaults.get("location_name") or ""),
            placeholder="Display name, for example: River",
            max_length=80,
        )
        self.items_drop_rate = discord.ui.TextInput(
            label="Item drop chance",
            default=str(Decimal(str(defaults.get("items_drop_rate", "0.1"))) * 100),
            placeholder="Human percentage from 0 to 100, for example: 10",
            max_length=32,
        )
        self.level = discord.ui.TextInput(
            label="Minimum level",
            default=str((defaults.get("requirements") or {}).get("level") or ""),
            placeholder="Optional integer from 0 to 1000000",
            required=False,
            max_length=16,
        )
        self.total_fish_stat = discord.ui.TextInput(
            label="Minimum total fish",
            default=str((defaults.get("requirements") or {}).get("total_fish_stat") or ""),
            placeholder="Optional integer from 0 to 1000000000",
            required=False,
            max_length=20,
        )
        for item in (
            self.location_id,
            self.location_name,
            self.items_drop_rate,
            self.level,
            self.total_fish_stat,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            payload = {
                "location_id": self.location_id.value.strip(),
                "location_name": self.location_name.value.strip(),
                "items_drop_rate": parse_decimal(
                    str(Decimal(self.items_drop_rate.value.strip()) / 100)
                ),
                "requirements": {},
            }
            if self.level.value.strip():
                payload["requirements"]["level"] = int(self.level.value)
            if self.total_fish_stat.value.strip():
                payload["requirements"]["total_fish_stat"] = int(self.total_fish_stat.value)
            if self.expected_version is not None:
                payload["expected_version"] = self.expected_version
                payload.pop("location_id")
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        await interaction.response.send_modal(
            LocationMassRequirementModal(payload, self.on_save, self.defaults)
        )


class LocationMassRequirementModal(discord.ui.Modal):
    def __init__(self, payload: dict[str, Any], on_save, defaults: dict[str, Any]):
        super().__init__(title="Location mass requirement")
        self.payload = payload
        self.on_save = on_save
        self.total_mass_stat = discord.ui.TextInput(
            label="Minimum total mass (kg)",
            default=str((defaults.get("requirements") or {}).get("total_mass_stat") or ""),
            placeholder="Optional mass in kg; leave empty for no requirement",
            required=False,
            max_length=32,
        )
        self.add_item(self.total_mass_stat)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            payload = {**self.payload, "requirements": dict(self.payload["requirements"])}
            if self.total_mass_stat.value.strip():
                payload["requirements"]["total_mass_stat"] = parse_decimal(
                    self.total_mass_stat.value
                )
            else:
                payload["requirements"]["total_mass_stat"] = None
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        async def confirm(confirm_interaction: discord.Interaction) -> None:
            await self.on_save(confirm_interaction, payload)

        await _show_preview(interaction, "Location preview", payload, confirm)


class ItemDropModal(discord.ui.Modal):
    def __init__(
        self,
        on_save,
        previewer,
        location_id: str,
        item_id: str,
        *,
        action: str,
        stackable: bool = False,
        defaults: dict[str, Any] | None = None,
    ):
        defaults = defaults or {}
        super().__init__(title="Edit item drop" if defaults else "Add item drop")
        self.on_save = on_save
        self.previewer = previewer
        self.location_id = location_id
        self.item_id = item_id
        self.action = action
        self.stackable = stackable
        self.current = defaults or None
        self.weight = discord.ui.TextInput(
            label="Weight",
            default=str(defaults.get("weight", 100)),
            placeholder="Relative selection weight from 1 to 1000000",
            max_length=16,
        )
        self.xp_gain = discord.ui.TextInput(
            label="XP gain",
            default=str(defaults.get("xp_gain", 0)),
            placeholder="Extra XP from 0 to 1000000",
            max_length=16,
        )
        self.quantity = discord.ui.TextInput(
            label="Stock",
            default="" if defaults.get("quantity") is None else str(defaults["quantity"]),
            placeholder="Finite stock; leave empty for unlimited",
            required=False,
            max_length=16,
        )
        self.message = discord.ui.TextInput(
            label="Chat message",
            default=str(defaults.get("message") or ""),
            placeholder="Use {name} for the item title",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=200,
        )
        for item in (self.weight, self.xp_gain, self.quantity, self.message):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            payload = self._parse_payload()
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        if self.stackable:
            await interaction.response.send_modal(
                ItemDropQuantityModal(
                    on_save=self.on_save,
                    previewer=self.previewer,
                    location_id=self.location_id,
                    item_id=self.item_id,
                    action=self.action,
                    payload=payload,
                    defaults=self.current or {},
                )
            )
            return
        try:
            preview = await self.previewer(interaction, payload)
        except EngineError as error:
            await interaction.response.send_message(
                localize_error(error), ephemeral=True
            )
            return

        async def confirm(confirm_interaction: discord.Interaction) -> None:
            await self.on_save(confirm_interaction, payload)

        embed = item_drop_preview_embed(
            action=self.action,
            location_id=self.location_id,
            preview=preview,
            payload=payload,
            current=self.current,
        )
        await interaction.response.send_message(
            embed=embed,
            view=ConfirmView(interaction.user.id, confirm),
            ephemeral=True,
        )

    def _parse_payload(self) -> dict[str, Any]:
        weight = self._parse_int(
            self.weight.value, "Weight", 1, 1_000_000, required=True
        )
        xp_gain = self._parse_int(self.xp_gain.value, "XP gain", 0, 1_000_000)
        quantity_text = self.quantity.value.strip()
        quantity = (
            None
            if not quantity_text
            else self._parse_int(self.quantity.value, "Stock", 0, 1_000_000_000)
        )
        return {
            "item_id": self.item_id,
            "weight": weight,
            "xp_gain": xp_gain,
            "quantity": quantity,
            "min_quantity": 1,
            "max_quantity": 1,
            "message": self.message.value.strip() or None,
        }

    @staticmethod
    def _parse_int(
        value: str,
        label: str,
        minimum: int,
        maximum: int,
        *,
        required: bool = False,
    ) -> int:
        text = value.strip()
        if not text:
            if required:
                raise ValueError(f"{label} is required")
            return minimum
        try:
            parsed = int(text)
        except ValueError as error:
            raise ValueError(f"{label} must be an integer") from error
        if not minimum <= parsed <= maximum:
            raise ValueError(f"{label} must be between {minimum} and {maximum}")
        return parsed


class ItemDropQuantityModal(discord.ui.Modal):
    def __init__(
        self,
        *,
        on_save,
        previewer,
        location_id: str,
        item_id: str,
        action: str,
        payload: dict[str, Any],
        defaults: dict[str, Any],
    ):
        super().__init__(title="Item drop quantity range")
        self.on_save = on_save
        self.previewer = previewer
        self.location_id = location_id
        self.item_id = item_id
        self.action = action
        self.payload = payload
        self.defaults = defaults
        self.min_quantity = discord.ui.TextInput(
            label="Minimum quantity",
            default=str(defaults.get("min_quantity", 1)),
            placeholder="Integer from 1 to 1000000000",
            max_length=16,
        )
        self.max_quantity = discord.ui.TextInput(
            label="Maximum quantity",
            default=str(defaults.get("max_quantity", 1)),
            placeholder="Must be at least the minimum quantity",
            max_length=16,
        )
        self.add_item(self.min_quantity)
        self.add_item(self.max_quantity)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            minimum = ItemDropModal._parse_int(
                self.min_quantity.value, "Minimum quantity", 1, 1_000_000_000, required=True
            )
            maximum = ItemDropModal._parse_int(
                self.max_quantity.value, "Maximum quantity", 1, 1_000_000_000, required=True
            )
            if maximum < minimum:
                raise ValueError("Maximum quantity must not be below minimum quantity")
            payload = {**self.payload, "min_quantity": minimum, "max_quantity": maximum}
            preview = await self.previewer(interaction, payload)
        except (EngineError, ValueError) as error:
            await interaction.response.send_message(
                localize_error(error) if isinstance(error, EngineError) else str(error),
                ephemeral=True,
            )
            return

        async def confirm(confirm_interaction: discord.Interaction) -> None:
            await self.on_save(confirm_interaction, payload)

        embed = item_drop_preview_embed(
            action=self.action,
            location_id=self.location_id,
            preview=preview,
            payload=payload,
            current=self.defaults,
        )
        await interaction.response.send_message(
            embed=embed,
            view=ConfirmView(interaction.user.id, confirm),
            ephemeral=True,
        )


def create_reward_modal(
    reward_type: str,
    on_save,
    defaults: dict[str, Any] | None = None,
) -> discord.ui.Modal:
    defaults = defaults or {}
    factories = {
        "fish": lambda: FishRewardModal(on_save, defaults),
        "timeout": lambda: TimeoutRewardModal(on_save, defaults),
        "robbery": lambda: RobberyRewardModal(on_save, defaults),
        "russian_roulette": lambda: RouletteSettingsModal(on_save, defaults),
        "dupe": lambda: DupeRewardModal(on_save, defaults),
        "nothing": lambda: RewardModal("nothing", {}, on_save, defaults),
    }
    try:
        return factories[reward_type]()
    except KeyError as error:
        raise ValueError("Unknown reward type") from error


class RewardModal(discord.ui.Modal):
    def __init__(
        self,
        reward_type: str,
        type_payload: dict[str, Any],
        on_save,
        defaults: dict[str, Any] | None = None,
    ):
        defaults = defaults or {}
        super().__init__(title=f"Reward details: {reward_type.replace('_', ' ')}")
        self.reward_type = reward_type
        self.type_payload = type_payload
        self.on_save = on_save
        self.name = discord.ui.TextInput(
            label="Name",
            default=str(defaults.get("name") or ""),
            placeholder="Optional display name",
            required=False,
            max_length=80,
        )
        self.weight = discord.ui.TextInput(
            label="Weight",
            default=str(defaults.get("weight", 100)),
            placeholder="Integer from 1 to 1000000",
            max_length=16,
        )
        self.xp = discord.ui.TextInput(
            label="XP",
            default=str(defaults.get("xp", 0)),
            placeholder="Experience reward from 0 to 1000000",
            max_length=16,
        )
        self.message = discord.ui.TextInput(
            label="Message",
            default=str(defaults.get("message") or ""),
            placeholder="Optional chat message for this reward",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=300,
        )
        for item in (self.name, self.weight, self.xp, self.message):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            base_payload = build_reward_base_payload(
                self.reward_type,
                self.name.value,
                self.weight.value,
                self.xp.value,
                self.message.value,
            )
        except (TypeError, ValueError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        payload = {**self.type_payload, **base_payload}
        await _show_reward_preview(interaction, payload, self.on_save)


class FishRewardModal(discord.ui.Modal):
    def __init__(self, on_save, defaults: dict[str, Any]):
        super().__init__(title="Fish reward settings")
        self.on_save = on_save
        self.defaults = defaults
        self.fixed_mass = _optional_input(
            "Fixed mass",
            defaults.get("fixed_mass"),
            "Use only this field; negative mass is allowed",
        )
        self.min_mass = _optional_input(
            "Minimum mass",
            defaults.get("min_mass"),
            "Fill with maximum mass for range mode",
        )
        self.max_mass = _optional_input(
            "Maximum mass",
            defaults.get("max_mass"),
            "Fill with minimum mass for range mode",
        )
        self.percentage = _optional_input(
            "Percentage",
            _display_human_percentage(defaults.get("percentage")),
            "Human percentage from -100 to 100, for example: -15",
        )
        for item in (self.fixed_mass, self.min_mass, self.max_mass, self.percentage):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await _continue_to_reward_details(
            interaction,
            "fish",
            {
                "fixed_mass": self.fixed_mass.value,
                "min_mass": self.min_mass.value,
                "max_mass": self.max_mass.value,
                "percentage": self.percentage.value,
            },
            self.on_save,
            self.defaults,
        )


class TimeoutRewardModal(discord.ui.Modal):
    def __init__(self, on_save, defaults: dict[str, Any]):
        super().__init__(title="Timeout reward settings")
        self.on_save = on_save
        self.defaults = defaults
        self.duration = discord.ui.TextInput(
            label="Duration",
            default=str(defaults.get("duration") or ""),
            placeholder="Seconds or duration, for example: 10m, 2h, 1d",
            max_length=16,
        )
        self.reason = _optional_input(
            "Reason",
            defaults.get("reason"),
            "Optional Twitch timeout reason",
            max_length=200,
        )
        self.add_item(self.duration)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await _continue_to_reward_details(
            interaction,
            "timeout",
            {"duration": self.duration.value, "reason": self.reason.value},
            self.on_save,
            self.defaults,
        )


class DupeRewardModal(discord.ui.Modal):
    def __init__(self, on_save, defaults: dict[str, Any]):
        super().__init__(title="Repeat fishing settings")
        self.on_save = on_save
        self.defaults = defaults
        self.amount = discord.ui.TextInput(
            label="Repeat count",
            default=str(defaults.get("amount", 1)),
            placeholder="Additional casts from 1 to 20",
            max_length=2,
        )
        self.delay = discord.ui.TextInput(
            label="Delay between casts",
            default=str(defaults.get("delay", 0)),
            placeholder="Seconds from 0 to 60",
            max_length=2,
        )
        self.add_item(self.amount)
        self.add_item(self.delay)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await _continue_to_reward_details(
            interaction,
            "dupe",
            {"amount": self.amount.value, "delay": self.delay.value},
            self.on_save,
            self.defaults,
        )


class RobberyRewardModal(discord.ui.Modal):
    def __init__(self, on_save, defaults: dict[str, Any]):
        super().__init__(title="Robbery reward settings")
        self.on_save = on_save
        self.defaults = defaults
        self.mass = _optional_input(
            "Fixed mass",
            defaults.get("mass"),
            "Use this field or percentage, not both",
        )
        self.percentage = _optional_input(
            "Percentage",
            _display_human_percentage(defaults.get("percentage")),
            "Human percentage from 0 to 100; leave mass empty",
        )
        self.search_range = discord.ui.TextInput(
            label="Victim search range",
            default=str(defaults.get("range", 3)),
            placeholder="Number of nearby users from 1 to 100",
            max_length=3,
        )
        self.success_message = _optional_input(
            "Success message",
            defaults.get("success_message"),
            "Optional; use {attacker}, {victim}, {attacker_gain}",
            max_length=300,
            paragraph=True,
        )
        for item in (self.mass, self.percentage, self.search_range, self.success_message):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await _continue_to_reward_details(
            interaction,
            "robbery",
            {
                "mass": self.mass.value,
                "percentage": self.percentage.value,
                "range": self.search_range.value,
                "success_message": self.success_message.value,
            },
            self.on_save,
            self.defaults,
        )


class RouletteSettingsModal(discord.ui.Modal):
    def __init__(self, on_save, defaults: dict[str, Any]):
        super().__init__(title="Russian roulette settings")
        self.on_save = on_save
        self.defaults = defaults
        self.bullets = discord.ui.TextInput(
            label="Bullets",
            default=str(defaults.get("bullets", 1)),
            placeholder="Integer from 1 to 6",
            max_length=1,
        )
        self.chambers = discord.ui.TextInput(
            label="Chambers",
            default=str(defaults.get("chambers", 6)),
            placeholder="Integer from 1 to 100; at least bullets",
            max_length=3,
        )
        self.safe_message = _optional_input(
            "Safe message",
            defaults.get("safe_message"),
            "Optional message when the chamber is safe",
            max_length=300,
            paragraph=True,
        )
        self.shot_message = _optional_input(
            "Shot message",
            defaults.get("shot_message"),
            "Optional message when the user is shot",
            max_length=300,
            paragraph=True,
        )
        for item in (self.bullets, self.chambers, self.safe_message, self.shot_message):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            payload = complete_reward_payload(
                {"type": "russian_roulette", "weight": 1, "xp": 0, "message": ""},
                {
                    "bullets": self.bullets.value,
                    "chambers": self.chambers.value,
                    "safe_message": self.safe_message.value,
                    "shot_message": self.shot_message.value,
                },
            )
        except (TypeError, ValueError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        view = ModalLauncherView(
            interaction.user.id,
            lambda: RouletteOutcomeModal(
                "reward", payload, self.on_save, self.defaults.get("reward") or {}, self.defaults
            ),
            label="Set success effect",
        )
        await interaction.response.send_message(
            "Roulette draft updated. Configure the optional success effect.",
            view=view,
            ephemeral=True,
        )


class RouletteOutcomeModal(discord.ui.Modal):
    def __init__(
        self,
        outcome_name: str,
        payload: dict[str, Any],
        on_save,
        outcome_defaults: dict[str, Any],
        reward_defaults: dict[str, Any],
    ):
        super().__init__(title=f"Roulette {outcome_name} effect")
        self.outcome_name = outcome_name
        self.payload = payload
        self.on_save = on_save
        self.reward_defaults = reward_defaults
        self.effect_type = discord.ui.TextInput(
            label="Effect type",
            default=str(outcome_defaults.get("type") or "none"),
            placeholder="none, add_mass, add_percentage_mass, or timeout",
            max_length=24,
        )
        self.mass = _optional_input(
            "Mass",
            outcome_defaults.get("mass"),
            "Used only for add_mass; negatives are allowed",
        )
        self.percentage = _optional_input(
            "Percentage",
            _display_human_percentage(outcome_defaults.get("percentage")),
            "Human percentage from -100 to 100 for add_percentage_mass",
        )
        self.duration = _optional_input(
            "Timeout duration",
            outcome_defaults.get("duration"),
            "Seconds or duration such as 10m; used for timeout",
            max_length=16,
        )
        self.reason = _optional_input(
            "Timeout reason",
            outcome_defaults.get("reason"),
            "Optional reason used only for timeout",
            max_length=200,
        )
        for item in (self.effect_type, self.mass, self.percentage, self.duration, self.reason):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            outcome = build_roulette_outcome(
                self.effect_type.value,
                self.mass.value,
                self.percentage.value,
                self.duration.value,
                self.reason.value,
            )
        except (TypeError, ValueError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        payload = dict(self.payload)
        if outcome is None:
            payload.pop(self.outcome_name, None)
        else:
            payload[self.outcome_name] = outcome

        if self.outcome_name == "reward":
            penalty_defaults = self.reward_defaults.get("penalty") or {}
            view = ModalLauncherView(
                interaction.user.id,
                lambda: RouletteOutcomeModal(
                    "penalty", payload, self.on_save, penalty_defaults, self.reward_defaults
                ),
                label="Set failure effect",
            )
            await interaction.response.send_message(
                "Success effect draft updated. Configure the optional failure effect.",
                view=view,
                ephemeral=True,
            )
            return
        await _show_reward_details_step(
            interaction,
            "russian_roulette",
            payload,
            self.on_save,
            self.reward_defaults,
        )


class EventModal(discord.ui.Modal):
    def __init__(self, on_save, defaults: dict[str, Any] | None = None):
        defaults = defaults or {}
        modifiers = defaults.get("modifiers") or {}
        super().__init__(title="Edit event" if defaults else "New event")
        self.on_save = on_save
        self.defaults = defaults
        self.title_input = discord.ui.TextInput(
            label="Name",
            default=str(defaults.get("event_title") or ""),
            placeholder="Event display name",
            max_length=120,
        )
        self.override_location = _optional_input(
            "Override location",
            defaults.get("override_loot_pool"),
            "Optional location ID, for example: lake",
            max_length=32,
        )
        self.fish_luck = _percent_input(
            "Fish luck change",
            modifiers.get("fish_luck_change_percent"),
            "Ordinary percentage; 10 = +10%, -20 = -20%",
        )
        self.positive_reward = _percent_input(
            "Positive reward change",
            modifiers.get("positive_fish_reward_change_percent"),
            "Ordinary percentage; 10 = +10%",
        )
        self.negative_reward = _percent_input(
            "Negative reward change",
            modifiers.get("negative_fish_reward_change_percent"),
            "Ordinary percentage; -15 = -15%",
        )
        for item in (
            self.title_input,
            self.override_location,
            self.fish_luck,
            self.positive_reward,
            self.negative_reward,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            payload = {
                "event_title": self.title_input.value.strip(),
                "override_loot_pool": self.override_location.value.strip() or None,
                "modifiers": {
                    "schema_version": 2,
                    "fish_luck_change_percent": _bounded_decimal(
                        self.fish_luck.value, "Fish luck change", -50, 100
                    ),
                    "positive_fish_reward_change_percent": _bounded_decimal(
                        self.positive_reward.value, "Positive reward change", -50, 200
                    ),
                    "negative_fish_reward_change_percent": _bounded_decimal(
                        self.negative_reward.value, "Negative reward change", -100, 100
                    ),
                },
            }
            if self.defaults.get("version") is not None:
                payload["expected_version"] = self.defaults["version"]
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        view = ModalLauncherView(
            interaction.user.id,
            lambda: EventModifiersModal(payload, self.on_save, self.defaults),
            label="Set XP and cooldown",
        )
        await interaction.response.send_message(
            "Event draft updated. Continue with XP and cooldown.",
            view=view,
            ephemeral=True,
        )


class EventModifiersModal(discord.ui.Modal):
    def __init__(self, payload: dict[str, Any], on_save, defaults: dict[str, Any]):
        super().__init__(title="Event XP and cooldown")
        self.payload = payload
        self.on_save = on_save
        modifiers = defaults.get("modifiers") or {}
        self.xp_gain = _percent_input(
            "XP gain change",
            modifiers.get("xp_gain_change_percent"),
            "Ordinary percentage; 100 = +100%",
        )
        self.cooldown_change = _percent_input(
            "Cooldown change",
            modifiers.get("cooldown_change_percent"),
            "Ordinary percentage; -50 = -50%",
        )
        self.add_item(self.xp_gain)
        self.add_item(self.cooldown_change)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            payload = {
                **self.payload,
                "modifiers": {
                    **self.payload["modifiers"],
                    "xp_gain_change_percent": _bounded_decimal(
                        self.xp_gain.value, "XP gain change", -100, 400
                    ),
                    "cooldown_change_percent": _bounded_decimal(
                        self.cooldown_change.value, "Cooldown change", -80, 100
                    ),
                },
            }
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        view = ModalLauncherView(
            interaction.user.id,
            lambda: EventRiskModifiersModal(payload, self.on_save, self.defaults),
            label="Set item-drop and robbery modifiers",
        )
        await interaction.response.send_message(
            "Event draft updated. Continue with item-drop and robbery modifiers.",
            view=view,
            ephemeral=True,
        )


class EventRiskModifiersModal(discord.ui.Modal):
    def __init__(self, payload: dict[str, Any], on_save, defaults: dict[str, Any]):
        super().__init__(title="Event item-drop and robbery")
        self.payload = payload
        self.on_save = on_save
        modifiers = defaults.get("modifiers") or {}
        self.item_drop = _percent_input(
            "Item drop chance (pp)",
            modifiers.get("item_drop_chance_add_pp"),
            "Percentage points; 5 means +5 percentage points",
        )
        self.item_rarity = _percent_input(
            "Item rarity luck",
            modifiers.get("item_rarity_luck_change_percent"),
            "Ordinary percentage; 10 = +10%",
        )
        self.robbery_protection = _percent_input(
            "Robbery protection",
            modifiers.get("robbery_protection_percent"),
            "Ordinary percentage from 0 to 100",
        )
        self.robbery_evasion = _percent_input(
            "Robbery evasion",
            modifiers.get("robbery_evasion_percent"),
            "Ordinary percentage from 0 to 100",
        )
        for item in (
            self.item_drop,
            self.item_rarity,
            self.robbery_protection,
            self.robbery_evasion,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            payload = {
                **self.payload,
                "modifiers": {
                    **self.payload["modifiers"],
                    "item_drop_chance_add_pp": _bounded_decimal(
                        self.item_drop.value, "Item drop chance", -100, 100
                    ),
                    "item_rarity_luck_change_percent": _bounded_decimal(
                        self.item_rarity.value, "Item rarity luck", -100, 200
                    ),
                    "robbery_protection_percent": _bounded_decimal(
                        self.robbery_protection.value, "Robbery protection", 0, 100
                    ),
                    "robbery_evasion_percent": _bounded_decimal(
                        self.robbery_evasion.value, "Robbery evasion", 0, 100
                    ),
                },
            }
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        async def confirm(confirm_interaction: discord.Interaction) -> None:
            await self.on_save(confirm_interaction, payload)

        await _show_preview(interaction, "Event preview", payload, confirm)


async def _continue_to_reward_details(
    interaction: discord.Interaction,
    reward_type: str,
    parameters: dict[str, Any],
    on_save,
    defaults: dict[str, Any],
) -> None:
    try:
        payload = complete_reward_payload(
            {"type": reward_type, "weight": 1, "xp": 0, "message": ""},
            parameters,
        )
    except (TypeError, ValueError) as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    await _show_reward_details_step(
        interaction,
        reward_type,
        payload,
        on_save,
        defaults,
    )


async def _show_reward_details_step(
    interaction: discord.Interaction,
    reward_type: str,
    type_payload: dict[str, Any],
    on_save,
    defaults: dict[str, Any],
) -> None:
    view = ModalLauncherView(
        interaction.user.id,
        lambda: RewardModal(reward_type, type_payload, on_save, defaults),
        label="Open reward details",
    )
    await interaction.response.send_message(
        "Type-specific draft updated. Continue with name, weight, XP, and message.",
        view=view,
        ephemeral=True,
    )


async def _show_reward_preview(
    interaction: discord.Interaction,
    payload: dict[str, Any],
    on_save,
) -> None:
    async def confirm(confirm_interaction: discord.Interaction) -> None:
        await on_save(confirm_interaction, payload)

    await _show_preview(interaction, "Reward preview", payload, confirm)


async def _show_preview(
    interaction: discord.Interaction,
    title: str,
    payload: dict[str, Any],
    on_confirm,
) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    limit = 3800
    if len(rendered) > limit:
        # Never truncate silently: technical JSON beyond the embed limit is
        # attached as a file with a compact summary in the embed.
        summary = json.dumps(payload, ensure_ascii=False, indent=2)[:1000]
        file = discord.File(
            io.BytesIO(rendered.encode("utf-8")), filename="preview.json"
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                title=title,
                description=(
                    "Full JSON is attached as `preview.json` "
                    f"({len(rendered)} chars).\n```json\n{summary}\n```"
                ),
                color=discord.Color.orange(),
            ),
            file=file,
            view=ConfirmView(interaction.user.id, on_confirm),
            ephemeral=True,
        )
        return
    await interaction.response.send_message(
        embed=discord.Embed(
            title=title,
            description=f"```json\n{rendered}\n```",
            color=discord.Color.orange(),
        ),
        view=ConfirmView(interaction.user.id, on_confirm),
        ephemeral=True,
    )


def _optional_input(
    label: str,
    default: Any,
    placeholder: str,
    *,
    max_length: int = 32,
    paragraph: bool = False,
) -> discord.ui.TextInput:
    return discord.ui.TextInput(
        label=label,
        default="" if default is None else str(default),
        placeholder=placeholder,
        style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short,
        required=False,
        max_length=max_length,
    )


def _display_human_percentage(value: Any) -> str | None:
    """Convert a stored ratio to the percentage shown in Discord forms."""
    if value is None or not str(value).strip():
        return None
    number = ratio_to_percent(Decimal(str(value)))
    if number == number.to_integral_value():
        return str(int(number))
    return format(number, "f").rstrip("0").rstrip(".")


def _percent_input(
    label: str,
    default: Any,
    placeholder: str,
) -> discord.ui.TextInput:
    return discord.ui.TextInput(
        label=label,
        default="0" if default is None else str(default),
        placeholder=placeholder,
        style=discord.TextStyle.short,
        required=True,
        max_length=16,
    )


def _bounded_decimal(
    value: str,
    label: str,
    minimum: int | Decimal,
    maximum: int | Decimal,
) -> str:
    parsed = parse_decimal(value)
    numeric = Decimal(parsed)
    if not Decimal(str(minimum)) <= numeric <= Decimal(str(maximum)):
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return parsed


def _schema_constraint(field_schema: dict[str, Any]) -> str | None:
    candidates = [field_schema, *field_schema.get("anyOf", [])]
    numeric = next(
        (candidate for candidate in candidates if "minimum" in candidate or "maximum" in candidate),
        None,
    )
    if not numeric:
        return None
    return f"Range: {numeric.get('minimum', '-inf')} to {numeric.get('maximum', 'inf')}"
