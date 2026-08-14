"""Item Effects step — category-driven editor (wizard spec §12/§21/§34/§35).

``ItemEffectsView`` is the standard effects editor used by the item wizard. It
replaces the raw effect-type select with a human flow:

1. pick a category (Fishing / Item Drop / Robbery / Inventory /
   Triggered / Advanced);
2. pick a stat or triggered effect inside that category;
3. enter values in a typed modal with human labels and units (no StatKey, no
   ratio input, no comma-separated lists, no raw JSON).

Triggered effects that reference channel entities (``grant_item``,
``loot_table_roll``) load their options from the current channel through the
admin API (spec §27/§30/§62). The editor refreshes its own message in place
after every change (spec §34) and keeps the list capped at
``STANDARD_MAX_EFFECTS`` in standard mode / ``ADVANCED_MAX_EFFECTS`` in
advanced mode (spec §35).
"""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

import discord

from app.domain.item_effect_registry import (
    ADVANCED_MAX_EFFECTS,
    CATEGORY_ADVANCED,
    EFFECT_CATEGORIES,
    CATEGORY_TRIGGERED,
    has_duplicate_effect,
    STANDARD_MAX_EFFECTS,
    TRIGGERED_EFFECT_FORMS,
    TRIGGERED_EFFECT_OPTIONS,
    UI_STAT_DEFINITIONS,
    describe_effect,
)
from app.interactions.items.effect_forms import (
    EffectNumbersModal,
    StatMultiplyModal,
    StatValueModal,
    load_entity_options,
)
from app.interactions.metrics import count_wizard_timeout


def _embed_for(title: str, description: str) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=discord.Color.gold())


def _auto_advanced(effects: list[dict]) -> bool:
    """A draft that already overflows the standard editor must open in advanced
    mode: legacy/imported items can have more than ``STANDARD_MAX_EFFECTS`` or
 carry advanced-only stats (``stat_multiply``)."""
    if len(effects) > STANDARD_MAX_EFFECTS:
        return True
    return any(
        effect.get("type") == "stat_multiply"
        for effect in effects
    )


class ItemEffectsView(discord.ui.View):
    """Standard list editor for a draft item's effects (spec §12/§34/§35).

    In standard mode the list is capped at ``STANDARD_MAX_EFFECTS`` (spec §35)
    and advanced stats are hidden behind a warning (spec §32). Once advanced
    mode is enabled the cap becomes ``ADVANCED_MAX_EFFECTS`` and low-level
    controls (``stat_multiply``) become reachable.
    """

    def __init__(
        self,
        initiator_id: int,
        effects: list[dict],
        on_done,
        *,
        api,
        on_back: Callable[[discord.Interaction], Awaitable[None]] | None = None,
        timeout: int = 600,
        restart_text: str = "Run /fish item create again.",
        advanced: bool = False,
        stat_metadata: dict[str, dict[str, Any]] | None = None,
    ):
        super().__init__(timeout=timeout)
        self.initiator_id = initiator_id
        self.effects: list[dict] = list(effects)
        self.on_done = on_done
        self.on_back = on_back
        self.api = api
        self._restart_text = restart_text
        self.stat_definitions = self._build_stat_definitions(stat_metadata or {})
        self._advanced = advanced or _auto_advanced(effects)
        self._selected_index: int | None = None
        self._validation_error: str | None = None
        self._rebuild_pick_options()
        self._update_buttons()

    @staticmethod
    def _build_stat_definitions(
        metadata: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Overlay engine-provided units and human bounds on the UI registry."""
        definitions = dict(UI_STAT_DEFINITIONS)
        for stat_key, definition in definitions.items():
            contract = metadata.get(stat_key)
            if not contract:
                continue
            unit = definition.unit
            if contract.get("unit") == "kg":
                unit = "mass_kg"
            elif contract.get("unit") == "slots":
                unit = "flat"
            definitions[stat_key] = replace(
                definition,
                unit=unit,
                value_type=contract.get("value_type", definition.value_type),
                display_min=str(contract.get("minimum", definition.display_min)),
                display_max=str(contract.get("maximum", definition.display_max)),
                helper=contract.get("description", definition.helper),
            )
        return definitions

    def stat_definition(self, stat_key: str):
        definition = self.stat_definitions.get(stat_key)
        if definition is not None:
            return definition
        return UI_STAT_DEFINITIONS[stat_key]

    # --- presentation --------------------------------------------------------

    @property
    def _max_effects(self) -> int:
        return ADVANCED_MAX_EFFECTS if self._advanced else STANDARD_MAX_EFFECTS

    @property
    def _mode_label(self) -> str:
        return "Advanced editor" if self._advanced else "Standard editor"

    def _embed(self) -> discord.Embed:
        embed = _embed_for(
            "Item Effects",
            "Add typed effects by category — no JSON or StatKey needed. "
            "Pick an effect in the list to edit, remove, or move it.",
        )
        if not self.effects:
            embed.add_field(
                name="Effects",
                value="No effects have been added yet. Choose a category below to add an effect.",
                inline=False,
            )
        else:
            lines = []
            for index, effect in enumerate(self.effects, start=1):
                marker = "▸" if index - 1 == self._selected_index else " "
                lines.append(f"{marker} {index}. {describe_effect(effect)}")
            embed.add_field(name="Effects", value="\n".join(lines)[:1024], inline=False)
        if self._validation_error:
            embed.add_field(name="Validation", value=f"⚠ {self._validation_error}", inline=False)
        if len(self.effects) >= self._max_effects:
            embed.add_field(
                name="Effect limit",
                value=(
                    f"This item already has the maximum number of effects allowed "
                    f"in the {self._mode_label.lower()}."
                ),
                inline=False,
            )
        embed.set_footer(
            text=f"{len(self.effects)}/{self._max_effects} effect(s) · {self._mode_label}"
        )
        return embed

    @property
    def message_text(self) -> str:
        return "Assemble the item's effects."

    # --- owner guard -----------------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "These controls belong to another user.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        count_wizard_timeout("item_effects")
        if self.message is not None:
            await self.message.edit(
                content=f"⏱ The effects step expired. {self._restart_text}",
                view=self,
            )
        self.stop()

    # --- list controls ----------------------------------------------------------

    def _rebuild_pick_options(self) -> None:
        if not self.effects:
            self.pick_effect.options = [discord.SelectOption(label="No effects yet", value="-1")]
            self.pick_effect.disabled = True
            self.pick_effect.placeholder = "Add an effect first"
            return
        options = []
        for index, effect in enumerate(self.effects[:25]):
            options.append(
                discord.SelectOption(
                    label=describe_effect(effect)[:100] or "effect",
                    value=str(index),
                    description=f"Effect #{index + 1}",
                    default=(index == self._selected_index),
                )
            )
        self.pick_effect.options = options
        self.pick_effect.disabled = False
        self.pick_effect.placeholder = "Select an effect to edit/remove/move…"

    def _update_buttons(self) -> None:
        has_selection = self._selected_index is not None
        self.remove_selected.disabled = not has_selection
        self.edit_selected.disabled = not has_selection
        self.move_up.disabled = not has_selection or self._selected_index == 0
        self.move_down.disabled = (
            not has_selection
            or self._selected_index is None
            or self._selected_index >= len(self.effects) - 1
        )
        self.add_button.disabled = len(self.effects) >= self._max_effects
        self.advanced_mode.disabled = self._advanced

    async def show(self, interaction: discord.Interaction) -> None:
        """Re-render this editor on the same message (spec §34)."""
        self._rebuild_pick_options()
        self._update_buttons()
        await interaction.response.edit_message(content=None, embed=self._embed(), view=self)

    def _append(self, payload: dict) -> None:
        if has_duplicate_effect(self.effects, payload):
            self._validation_error = (
                f"Duplicate effect is not allowed: {describe_effect(payload)}."
            )
            self._rebuild_pick_options()
            self._update_buttons()
            return
        self.effects.append(payload)
        self._validation_error = None
        self._rebuild_pick_options()
        self._update_buttons()

    def _replace(self, index: int, payload: dict) -> None:
        if not 0 <= index < len(self.effects):
            return
        remaining = self.effects[:index] + self.effects[index + 1 :]
        if has_duplicate_effect(remaining, payload):
            self._validation_error = (
                f"Duplicate effect is not allowed: {describe_effect(payload)}."
            )
            self._rebuild_pick_options()
            self._update_buttons()
            return
        self.effects[index] = payload
        self._validation_error = None
        self._rebuild_pick_options()
        self._update_buttons()

    def _remove(self, index: int) -> None:
        del self.effects[index]
        self._selected_index = None
        self._validation_error = None
        self._rebuild_pick_options()
        self._update_buttons()

    async def _refresh_from(self, interaction: discord.Interaction) -> None:
        await self.show(interaction)

    @discord.ui.select(placeholder="Select an effect to edit/remove/move…", row=0)
    async def pick_effect(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        if select.values and select.values[0] == "-1":
            return
        self._selected_index = int(select.values[0]) if select.values else None
        self._rebuild_pick_options()
        self._update_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Edit selected", style=discord.ButtonStyle.secondary, row=1)
    async def edit_selected(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self._selected_index is None:
            return
        index = self._selected_index
        effect = self.effects[index]
        effect_type = str(effect.get("type") or "")
        commit = lambda payload: self._replace(index, payload)  # noqa: E731
        await self._open_effect_form(interaction, effect_type, current=effect, commit=commit)

    @discord.ui.button(label="Remove selected", style=discord.ButtonStyle.danger, row=1)
    async def remove_selected(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self._selected_index is None:
            return
        self._remove(self._selected_index)
        await self.show(interaction)

    @discord.ui.button(label="Move up", style=discord.ButtonStyle.secondary, row=1)
    async def move_up(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._selected_index is None or self._selected_index <= 0:
            return
        index = self._selected_index
        self.effects[index], self.effects[index - 1] = (
            self.effects[index - 1],
            self.effects[index],
        )
        self._selected_index = index - 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Move down", style=discord.ButtonStyle.secondary, row=1)
    async def move_down(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self._selected_index is None or self._selected_index >= len(self.effects) - 1:
            return
        index = self._selected_index
        self.effects[index], self.effects[index + 1] = (
            self.effects[index + 1],
            self.effects[index],
        )
        self._selected_index = index + 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)

    # --- add flow --------------------------------------------------------------

    @discord.ui.button(label="Add effect", style=discord.ButtonStyle.primary, row=2)
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if len(self.effects) >= self._max_effects:
            return
        picker = EffectCategoryPickerView(self)
        await interaction.response.edit_message(embed=picker._embed(), view=picker)

    @discord.ui.button(label="Advanced mode", style=discord.ButtonStyle.blurple, row=1)
    async def advanced_mode(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Spec §32/§35: warn before exposing the low-level advanced editor."""
        if self._advanced:
            return
        view = AdvancedModeWarningView(self, on_continue=lambda done: self.show(done))
        await interaction.response.edit_message(embed=view._embed(), view=view)

    # --- navigation -------------------------------------------------------------

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success, row=2)
    async def continue_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_done(interaction, list(self.effects))

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        if self.on_back is not None:
            await self.on_back(interaction)
        else:
            await self.on_done(interaction, None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=2)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_done(interaction, None)

    # --- typed form routing ------------------------------------------------------

    async def _open_effect_form(
        self,
        interaction: discord.Interaction,
        effect_type: str,
        *,
        current: dict | None = None,
        commit: Callable[[dict], None],
    ) -> None:
        current = current or {}
        if effect_type == "stat_add":
            stat = str(current.get("stat") or "")
            modal = StatValueModal(
                stat,
                commit,
                self._refresh_from,
                current=current.get("value"),
                definition=self.stat_definition(stat),
            )
            await interaction.response.send_modal(modal)
            return
        if effect_type == "stat_multiply":
            stat = str(current.get("stat") or "")
            modal = StatMultiplyModal(
                stat,
                commit,
                self._refresh_from,
                current=current.get("value"),
                definition=self.stat_definition(stat),
            )
            await interaction.response.send_modal(modal)
            return
        if effect_type in TRIGGERED_EFFECT_FORMS:
            await self._open_triggered_form(interaction, effect_type, current, commit)
            return
        # Unknown effect type: fall back to a plain stat form so an effect can
        # still be corrected without raw JSON.
        stat = str(current.get("stat") or "fish_luck_change_ratio")
        modal = StatValueModal(
            stat,
            commit,
            self._refresh_from,
            current=current.get("value"),
            definition=self.stat_definition(stat),
        )
        await interaction.response.send_modal(modal)

    async def _open_triggered_form(
        self,
        interaction: discord.Interaction,
        form_key: str,
        current: dict | None,
        commit: Callable[[dict], None],
    ) -> None:
        form = TRIGGERED_EFFECT_FORMS[form_key]
        entity_options: dict[str, list[tuple[str, str]]] = {}
        for field in form.fields:
            if field.kind == "entity":
                entity_options[field.key] = await load_entity_options(
                    self.api, interaction, field.entity
                )
        view = EffectFormView(
            self, form, entity_options=entity_options, current=current, commit=commit
        )
        await interaction.response.edit_message(embed=view._embed(), view=view)


class EffectCategoryPickerView(discord.ui.View):
    """Category → effect selection shown after ``Add effect`` (spec §12)."""

    def __init__(self, editor: ItemEffectsView, timeout: int = 600):
        super().__init__(timeout=timeout)
        self.editor = editor
        self.initiator_id = editor.initiator_id
        self._category: str | None = None
        self.category_select.options = [
            discord.SelectOption(label=label, value=value) for label, value in EFFECT_CATEGORIES
        ]
        self.effect_select.options = [
            discord.SelectOption(label="Choose a category first", value="-1")
        ]
        self.effect_select.disabled = True

    def _refresh_category_default(self) -> None:
        self.category_select.options = [
            discord.SelectOption(label=label, value=value, default=(value == self._category))
            for label, value in EFFECT_CATEGORIES
        ]

    def _embed(self) -> discord.Embed:
        return _embed_for(
            "Add an Effect",
            "Choose a category, then the exact effect you want to add.",
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "These controls belong to another user.", ephemeral=True
            )
            return False
        return True

    def _effect_options(self) -> list[discord.SelectOption]:
        category = self._category
        if category == CATEGORY_TRIGGERED:
            return [
                discord.SelectOption(label=label, value=value)
                for label, value in TRIGGERED_EFFECT_OPTIONS
                if not has_duplicate_effect(self.editor.effects, {"type": value})
            ]
        if category == CATEGORY_ADVANCED:
            return [
                discord.SelectOption(label=definition.label, value=definition.stat)
                for definition in self.editor.stat_definitions.values()
                if not (
                    has_duplicate_effect(
                        self.editor.effects,
                        {"type": "stat_add", "stat": definition.stat},
                    )
                    and has_duplicate_effect(
                        self.editor.effects,
                        {"type": "stat_multiply", "stat": definition.stat},
                    )
                )
            ]
        return [
            discord.SelectOption(label=definition.label, value=definition.stat)
            for definition in self.editor.stat_definitions.values()
            if definition.category == category
            if not has_duplicate_effect(
                self.editor.effects,
                {"type": "stat_add", "stat": definition.stat},
            )
        ]

    @discord.ui.select(placeholder="Choose a category…", min_values=1, max_values=1, row=0)
    async def category_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        self._category = select.values[0]
        self._refresh_category_default()
        if self._category == CATEGORY_ADVANCED and not self.editor._advanced:
            # Spec §32: entering the advanced flow shows the warning first;
            # Continue arms advanced mode and exposes the low-level stats.
            async def open_advanced(interaction: discord.Interaction) -> None:
                self._refresh_category_default()
                options = self._effect_options()
                self.effect_select.options = options or [
                    discord.SelectOption(label="No new effects available", value="-1")
                ]
                self.effect_select.disabled = not options
                await interaction.response.edit_message(embed=self._embed(), view=self)

            view = AdvancedModeWarningView(self.editor, on_continue=open_advanced)
            await interaction.response.edit_message(embed=view._embed(), view=view)
            return
        options = self._effect_options()
        self.effect_select.options = options or [
            discord.SelectOption(label="No new effects available", value="-1")
        ]
        self.effect_select.disabled = not options
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.select(placeholder="Choose an effect…", min_values=1, max_values=1, row=1)
    async def effect_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        picked = select.values[0]
        if picked == "-1":
            await self.editor.show(interaction)
            return
        category = self._category
        if category == CATEGORY_TRIGGERED:
            await self.editor._open_triggered_form(
                interaction, picked, current=None, commit=self.editor._append
            )
        elif category == CATEGORY_ADVANCED:
            view = AdvancedEffectPickerView(self.editor, picked)
            await interaction.response.edit_message(embed=view._embed(), view=view)
        else:
            modal = StatValueModal(
                picked,
                self.editor._append,
                self.editor._refresh_from,
                definition=self.editor.stat_definition(picked),
            )
            await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=2)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.editor.show(interaction)


class AdvancedModeWarningView(discord.ui.View):
    """Spec §32: warning shown before exposing the low-level advanced editor.

    Reached either from the editor's ``Advanced mode`` button (which raises the
    effect cap to ``ADVANCED_MAX_EFFECTS``, spec §35) or by picking the
    Advanced Effect category. Continue arms advanced mode and hands control to
    ``on_continue``; Cancel returns to the standard editor.
    """

    def __init__(
        self,
        editor: ItemEffectsView,
        *,
        on_continue: Callable[[discord.Interaction], Awaitable[None]] | None = None,
        timeout: int = 600,
    ):
        super().__init__(timeout=timeout)
        self.editor = editor
        self.initiator_id = editor.initiator_id
        self._on_continue = on_continue

    def _embed(self) -> discord.Embed:
        return _embed_for(
            "Advanced Effect",
            "This editor exposes low-level effect controls intended for "
            "experienced administrators.",
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "These controls belong to another user.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        count_wizard_timeout("item_advanced_warning")
        if self.message is not None:
            await self.message.edit(
                content=f"⏱ The advanced editor expired. {self.editor._restart_text}",
                view=self,
            )
        self.stop()

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success, row=0)
    async def continue_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.editor._advanced = True
        if self._on_continue is not None:
            await self._on_continue(interaction)
        else:
            await self.editor.show(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=0)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.editor.show(interaction)


class AdvancedEffectPickerView(discord.ui.View):
    """Operation picker for an advanced stat effect (spec §33)."""

    def __init__(self, editor: ItemEffectsView, stat_key: str, timeout: int = 600):
        super().__init__(timeout=timeout)
        self.editor = editor
        self.initiator_id = editor.initiator_id
        self.stat_key = stat_key
        self._operation: str | None = None
        definition = editor.stat_definition(stat_key)
        self._label = definition.label
        self.operation_select.options = [
            discord.SelectOption(label="Add", value="add", description=f"Change {self._label}"),
            discord.SelectOption(
                label="Multiply", value="multiply", description=f"Multiply {self._label}"
            ),
        ]
        available = []
        if not has_duplicate_effect(
            self.editor.effects, {"type": "stat_add", "stat": self.stat_key}
        ):
            available.append(
                discord.SelectOption(label="Add", value="add", description=f"Change {self._label}")
            )
        if not has_duplicate_effect(
            self.editor.effects, {"type": "stat_multiply", "stat": self.stat_key}
        ):
            available.append(
                discord.SelectOption(
                    label="Multiply", value="multiply", description=f"Multiply {self._label}"
                )
            )
        self.operation_select.options = available or [
            discord.SelectOption(label="No operations available", value="-1")
        ]
        self.operation_select.disabled = not available
        self.continue_button.disabled = True

    def _embed(self) -> discord.Embed:
        return _embed_for(
            f"Advanced: {self._label}",
            "Add changes the stat by a fixed amount; "
            "Multiply scales the resolved stat by a factor.",
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "These controls belong to another user.", ephemeral=True
            )
            return False
        return True

    @discord.ui.select(placeholder="Choose an operation…", min_values=1, max_values=1, row=0)
    async def operation_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        self._operation = select.values[0]
        if self._operation == "-1":
            return
        self.continue_button.disabled = False
        options = []
        if not has_duplicate_effect(
            self.editor.effects, {"type": "stat_add", "stat": self.stat_key}
        ):
            options.append(
                discord.SelectOption(
                    label="Add",
                    value="add",
                    description=f"Change {self._label}",
                    default=(self._operation == "add"),
                )
            )
        if not has_duplicate_effect(
            self.editor.effects, {"type": "stat_multiply", "stat": self.stat_key}
        ):
            options.append(
                discord.SelectOption(
                    label="Multiply",
                    value="multiply",
                    description=f"Multiply {self._label}",
                    default=(self._operation == "multiply"),
                )
            )
        self.operation_select.options = options
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success, row=1)
    async def continue_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self._operation == "multiply":
            modal = StatMultiplyModal(
                self.stat_key,
                self.editor._append,
                self.editor._refresh_from,
                definition=self.editor.stat_definition(self.stat_key),
            )
        else:
            modal = StatValueModal(
                self.stat_key,
                self.editor._append,
                self.editor._refresh_from,
                definition=self.editor.stat_definition(self.stat_key),
            )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.editor.show(interaction)


class EffectFormView(discord.ui.View):
    """Selects the structured fields of a triggered effect before the modal.

    Select/multiselect/entity fields are rendered as selects (spec §22-§26);
    the remaining number/text fields are collected by ``EffectNumbersModal``.
    """

    def __init__(
        self,
        editor: ItemEffectsView,
        form,
        *,
        entity_options: dict[str, list[tuple[str, str]]] | None = None,
        current: dict | None = None,
        commit: Callable[[dict], None] | None = None,
        timeout: int = 600,
    ):
        super().__init__(timeout=timeout)
        self.editor = editor
        self.form = form
        self.initiator_id = editor.initiator_id
        self.entity_options = entity_options or {}
        self.commit = commit or editor._append
        self._current = dict(current or {})
        self.select_values: dict[str, Any] = self._select_values_from_current(current)
        self.select_widgets: dict[str, discord.ui.Select] = {}
        self._build_select_fields(current)
        self._update_state()

    def _select_values_from_current(self, current: dict | None) -> dict[str, Any]:
        """Carry the effect's stored select values so editing keeps them (spec §34).

        ``robbery_counter`` stores its counter action in the nested ``action``
        object, so the ``action_type`` select reads from there.
        """
        values: dict[str, Any] = {}
        for field in self.form.fields:
            if field.kind not in ("select", "multiselect", "entity"):
                continue
            value = None
            if current:
                if field.key == "action_type":
                    value = (current.get("action") or {}).get("type")
                else:
                    value = current.get(field.key)
            if value is None:
                continue
            values[field.key] = (
                value if field.max_values == 1 else (value if isinstance(value, list) else [value])
            )
        return values

    def _build_select_fields(self, current: dict | None) -> None:
        row = 0
        for field in self.form.fields:
            if field.kind not in ("select", "multiselect", "entity"):
                continue
            options = self._options_for(field)
            select = discord.ui.Select(
                placeholder=self._placeholder_for(field),
                min_values=field.min_values,
                max_values=field.max_values,
                options=options,
                row=row,
            )
            select.callback = self._make_callback(field)
            self.add_item(select)
            self.select_widgets[field.key] = select
            if not options or (field.required and options[0].value == "-1"):
                select.disabled = True
            row += 1

    def _placeholder_for(self, field) -> str:
        value = self.select_values.get(field.key)
        if value is None:
            return field.label + "…"
        values = value if isinstance(value, list) else [value]
        labels = [self._label_for(field, item) for item in values]
        label = ", ".join(label for label in labels if label)
        return f"{field.label}: {label}"[:150]

    def _label_for(self, field, value: Any) -> str:
        for label, option_value in field.options:
            if str(option_value) == str(value):
                return label
        for label, option_value in self.entity_options.get(field.key) or []:
            if str(option_value) == str(value):
                return label
        return str(value)

    def _options_for(self, field) -> list[discord.SelectOption]:
        selected = self.select_values.get(field.key)
        selected_values = (
            {str(item) for item in selected} if isinstance(selected, list) else {str(selected)}
            if selected is not None
            else set()
        )
        if field.kind == "entity":
            options = [(label, value) for label, value in self.entity_options.get(field.key) or []]
            existing = {str(value) for _, value in options}
            current_values = self.select_values.get(field.key)
            if isinstance(current_values, str):
                current_values = [current_values]
            for value in current_values or []:
                if str(value) not in existing:
                    options.append((str(value), str(value)))
            if not options:
                return [discord.SelectOption(label="No choices available", value="-1")]
            return [
                discord.SelectOption(
                    label=label[:100] or "…", value=value, default=(str(value) in selected_values)
                )
                for label, value in options
            ]
        return [
            discord.SelectOption(
                label=label, value=value, default=(str(value) in selected_values)
            )
            for label, value in field.options
        ]

    def _make_callback(self, field) -> Callable[[discord.Interaction], Awaitable[None]]:
        async def callback(interaction: discord.Interaction) -> None:
            values = list(interaction.data.get("values") or [])
            if values == ["-1"]:
                return
            self.select_values[field.key] = values[0] if field.max_values == 1 else values
            self._update_state()
            widget = self.select_widgets.get(field.key)
            if widget is not None:
                widget.options = self._options_for(field)
            await interaction.response.edit_message(embed=self._embed(), view=self)

        return callback

    def _update_state(self) -> None:
        required = [
            field
            for field in self.form.fields
            if field.kind in ("select", "multiselect", "entity") and field.required
        ]
        missing = [field for field in required if field.key not in self.select_values]
        self.continue_button.disabled = bool(missing)

    def _embed(self) -> discord.Embed:
        return _embed_for(self.form.label, self.form.description or "Configure this effect.")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "These controls belong to another user.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        count_wizard_timeout("item_effect_form")
        if self.message is not None:
            await self.message.edit(
                content=f"⏱ The effect form expired. {self.editor._restart_text}",
                view=self,
            )
        self.stop()

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success, row=2)
    async def continue_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        modal = EffectNumbersModal(
            self.form,
            self.select_values,
            self.commit,
            self.editor._refresh_from,
            current=self._current or None,
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=2)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.editor.show(interaction)


__all__ = [
    "ItemEffectsView",
    "EffectCategoryPickerView",
    "AdvancedModeWarningView",
    "AdvancedEffectPickerView",
    "EffectFormView",
]
