"""Humanized typed effect forms (wizard spec §14-§33/§50).

Replaces the raw StatKey/ratio modals of ``effect_builder`` in the standard
wizard flow. Every value is entered in human units (``10`` = ten percent,
``0.5`` percentage points, kilograms, or flat counts) and converted to the
backend ratio/format through ``percent_helpers`` exactly once.
"""

from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import discord

from app.domain.item_effect_registry import (
    UNIT_MASS_KG,
    UNIT_PERCENT,
    UNIT_PERCENTAGE_POINTS,
    TRIGGERED_EFFECT_FORMS,
    UIStatDefinition,
    UI_STAT_DEFINITIONS,
    describe_effect,
)
from app.domain.percent_helpers import (
    percent_to_ratio,
    percentage_points_to_probability,
    probability_to_percentage_points,
    ratio_to_percent,
)

OnSave = Callable[[dict[str, Any]], None]
OnSaved = Callable[[discord.Interaction], Awaitable[None]] | None


def humanize_value(definition: UIStatDefinition, value: Any) -> str:
    """Convert a backend value to the human unit used in the form.

    Used to prefill the edit form with current values (spec §34).
    """
    try:
        number = Decimal(str(value))
    except Exception:
        return str(value)
    if definition.unit == UNIT_PERCENT:
        number = ratio_to_percent(number)
    elif definition.unit == UNIT_PERCENTAGE_POINTS:
        number = probability_to_percentage_points(number)
    if number == number.to_integral_value():
        return f"{int(number)}"
    return format(number, "f").rstrip("0").rstrip(".")


def human_value_to_backend(definition: UIStatDefinition, raw: str) -> tuple[str | None, str | None]:
    """Validate a human input against the display bounds and convert it.

    Returns ``(backend_value, error)``; exactly one is set.
    """
    raw = raw.strip()
    try:
        value = Decimal(raw)
    except Exception:
        return None, f"{definition.label} must be a number."
    try:
        if value < Decimal(definition.display_min):
            return None, f"{definition.label} must be at least {definition.display_min}."
        if value > Decimal(definition.display_max):
            return None, f"{definition.label} must be at most {definition.display_max}."
    except Exception:
        pass
    if value == 0:
        return None, f"{definition.label} must not be 0."
    if definition.value_type == "integer" and value != value.to_integral_value():
        return None, f"{definition.label} must be a whole number."
    if definition.unit == UNIT_PERCENT:
        return str(percent_to_ratio(value)), None
    if definition.unit == UNIT_PERCENTAGE_POINTS:
        return str(percentage_points_to_probability(value)), None
    return str(value), None


async def _finish_effect(
    interaction: discord.Interaction,
    payload: dict[str, Any],
    on_save: OnSave,
    on_saved: OnSaved,
) -> None:
    """Append/replace the effect and refresh the editor or acknowledge (spec §34)."""
    on_save(payload)
    if on_saved is not None:
        await on_saved(interaction)
    else:
        await interaction.response.send_message(
            f"Effect added: {describe_effect(payload)}", ephemeral=True
        )


class StatValueModal(discord.ui.Modal):
    """One human-labeled numeric field for a ``stat_add`` effect (spec §14-§20)."""

    def __init__(
        self,
        stat_key: str,
        on_save: OnSave,
        on_saved: OnSaved = None,
        *,
        current: Any = None,
    ):
        self.definition = UI_STAT_DEFINITIONS[stat_key]
        super().__init__(title=self.definition.label)
        self.on_save = on_save
        self.on_saved = on_saved
        self.value = discord.ui.TextInput(
            label=self.definition.input_label,
            placeholder=self.definition.helper,
            default=humanize_value(self.definition, current) if current is not None else "",
            required=True,
            max_length=24,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        backend_value, error = human_value_to_backend(self.definition, self.value.value)
        if error is not None:
            await interaction.response.send_message(error, ephemeral=True)
            return
        payload = {
            "type": "stat_add",
            "stat": self.definition.stat,
            "value": backend_value,
        }
        await _finish_effect(interaction, payload, self.on_save, self.on_saved)


class StatMultiplyModal(discord.ui.Modal):
    """Advanced: multiply a stat's resolved value (spec §33)."""

    def __init__(
        self,
        stat_key: str,
        on_save: OnSave,
        on_saved: OnSaved = None,
        *,
        current: Any = None,
    ):
        self.definition = UI_STAT_DEFINITIONS[stat_key]
        super().__init__(title=f"Multiply {self.definition.label}")
        self.on_save = on_save
        self.on_saved = on_saved
        self.multiplier = discord.ui.TextInput(
            label="Multiplier (1.5 = ×1.5)",
            placeholder="Advanced: changes the resolved stat by a factor.",
            default=humanize_value(self.definition, current) if current is not None else "1.5",
            required=True,
            max_length=12,
        )
        self.add_item(self.multiplier)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = self.multiplier.value.strip()
        try:
            value = Decimal(raw)
        except Exception:
            await interaction.response.send_message("Multiplier must be a number.", ephemeral=True)
            return
        if not 0 <= value <= 100:
            await interaction.response.send_message(
                "Multiplier must be between 0 and 100.", ephemeral=True
            )
            return
        if value == 1:
            await interaction.response.send_message(
                "Multiplier must not be 1 because it has no effect.", ephemeral=True
            )
            return
        payload = {
            "type": "stat_multiply",
            "stat": self.definition.stat,
            "value": str(value),
        }
        await _finish_effect(interaction, payload, self.on_save, self.on_saved)


def _modal_fields(form, select_values: dict[str, Any]) -> list:
    """The number/text fields to collect in the modal for a triggered effect.

    ``robbery_counter`` only asks for the field matching the chosen counter
    action instead of both timeout duration and attacker mass (spec §24).
    """
    fields = [field for field in form.fields if field.is_modal_field]
    if form.type == "robbery_counter":
        action_type = select_values.get("action_type", "timeout")
        fields = [
            field
            for field in fields
            if (action_type == "timeout" and field.key == "duration_seconds")
            or (action_type == "add_mass" and field.key == "attacker_mass_delta")
        ]
    return fields


def _modal_default(form, field, current: dict | None) -> str:
    """Prefill a modal input from the effect being edited (spec §34).

    ``robbery_counter`` stores its action fields in the nested ``action``
    object; every other effect keeps them flat under the field key. Percent
    ratios are shown back as human percentages.
    """
    value = None
    if current:
        if form.type == "robbery_counter" and field.key in (
            "duration_seconds",
            "attacker_mass_delta",
        ):
            value = (current.get("action") or {}).get(field.key)
        else:
            value = current.get(field.key)
    if value is None:
        value = field.default
    if value is None:
        return ""
    if field.unit == UNIT_PERCENT:
        number = ratio_to_percent(Decimal(str(value)))
        if number == number.to_integral_value():
            return f"{int(number)}"
        return format(number, "f").rstrip("0").rstrip(".")
    return str(value)


class EffectNumbersModal(discord.ui.Modal):
    """Collects the number/text fields of a triggered effect form."""

    def __init__(
        self,
        form,
        select_values: dict[str, Any],
        on_save: OnSave,
        on_saved: OnSaved = None,
        *,
        current: dict | None = None,
    ):
        super().__init__(title=form.label)
        self.form = form
        self.select_values = dict(select_values)
        self.on_save = on_save
        self.on_saved = on_saved
        self.inputs: dict[str, discord.ui.TextInput] = {}
        for field in _modal_fields(form, select_values):
            self.inputs[field.key] = discord.ui.TextInput(
                label=field.label,
                placeholder=field.placeholder or "",
                default=_modal_default(form, field, current),
                required=field.required,
                max_length=24 if field.kind == "number" else 200,
            )
            self.add_item(self.inputs[field.key])

    async def on_submit(self, interaction: discord.Interaction) -> None:
        modal_values: dict[str, Any] = {}
        errors: list[str] = []
        for field in _modal_fields(self.form, self.select_values):
            raw = self.inputs[field.key].value.strip()
            if field.kind == "text":
                modal_values[field.key] = raw or (
                    str(field.default) if field.default is not None else ""
                )
                continue
            converted, error = _modal_number_value(field, raw)
            if error is not None:
                errors.append(error)
                continue
            modal_values[field.key] = converted
        if errors:
            await interaction.response.send_message("\n".join(errors), ephemeral=True)
            return
        payload = build_triggered_payload(self.form.type, self.select_values, modal_values)
        await _finish_effect(interaction, payload, self.on_save, self.on_saved)


def _modal_number_value(field, raw: str) -> tuple[Any, str | None]:
    if not raw:
        if field.default is not None:
            raw = str(field.default)
        elif field.required:
            return None, f"{field.label} is required."
    try:
        value = Decimal(raw)
    except Exception:
        return None, f"{field.label} must be a number."
    if field.min is not None and value < Decimal(str(field.min)):
        return None, f"{field.label} must be at least {field.min}."
    if field.max is not None and value > Decimal(str(field.max)):
        return None, f"{field.label} must be at most {field.max}."
    if field.unit == UNIT_PERCENT:
        return str(percent_to_ratio(value)), None
    if field.unit == UNIT_MASS_KG:
        return str(value), None
    if value != value.to_integral_value():
        return None, f"{field.label} must be a whole number."
    return int(value), None


def build_triggered_payload(
    form_key: str, select_values: dict[str, Any], modal_values: dict[str, Any]
) -> dict[str, Any]:
    """Assemble the backend payload for a triggered effect from form values.

    Select/multiselect/entity values are taken verbatim; modal number values are
    already converted (ratios as ``Decimal`` strings); ``robbery_counter``
    builds its nested ``action`` object from the chosen counter action (spec §24).
    """
    form = TRIGGERED_EFFECT_FORMS[form_key]
    payload: dict[str, Any] = dict(form.defaults)
    payload["type"] = form.type
    for field in form.fields:
        if field.key in select_values:
            payload[field.key] = select_values[field.key]
        elif field.key in modal_values:
            payload[field.key] = modal_values[field.key]
    if form.type == "robbery_counter":
        action_type = payload.pop("action_type", "timeout")
        if action_type == "timeout":
            payload["action"] = {
                "type": "timeout",
                "duration_seconds": int(payload.pop("duration_seconds", 60)),
            }
        else:
            payload["action"] = {
                "type": "add_mass",
                "mass": str(payload.pop("attacker_mass_delta", "0")),
            }
    return payload


async def load_entity_options(
    api, interaction: discord.Interaction, entity: str
) -> list[tuple[str, str]]:
    """Load channel-scoped options for an entity reference (spec §27/§30/§62).

    Returns ``(label, value)`` pairs; an empty list means the reference cannot
    be chosen, and the caller shows the effect as unavailable.
    """
    try:
        if entity == "items":
            result = await api.items(interaction)
            return [
                (f"{entry['title']} ({entry['item_id']})", entry["item_id"])
                for entry in result.get("items") or []
            ]
        if entity == "loot_tables":
            result = await api.loot_tables(interaction)
            return [
                (f"{entry['title']} ({entry['table_id']})", entry["table_id"])
                for entry in result.get("items") or []
            ]
    except Exception:
        return []
    return []


__all__ = [
    "StatValueModal",
    "StatMultiplyModal",
    "EffectNumbersModal",
    "humanize_value",
    "human_value_to_backend",
    "build_triggered_payload",
    "load_entity_options",
]
