"""Editing view for a draft item effect list (no raw JSON in the primary UI)."""

import discord

from app.domain.item_effect_registry import has_duplicate_effect
from app.interactions.effect_builder import (
    EFFECT_SELECT_OPTIONS,
    describe_effect,
    modal_for_effect,
)
from app.interactions.metrics import count_wizard_timeout

# Spec §12/§35: the standard editor allows at most 10 effects so the list
# stays manageable in a Discord select. The advanced editor uses a separate
# (higher) limit; the backend may accept more for legacy/imported items.
STANDARD_MAX_EFFECTS = 10


class EffectsEditorView(discord.ui.View):
    """Lets an admin assemble the typed effects list for an item draft.

    The draft effects are stored in the wizard session by the caller; this view
    mutates the list in memory and returns the finished list via ``on_done``.
    An existing effect can be selected, replaced (edited), deleted, or moved
    up/down (audit 10.3).
    """

    def __init__(
        self,
        initiator_id: int,
        effects: list[dict],
        on_done,
        *,
        timeout: int = 600,
    ):
        super().__init__(timeout=timeout)
        self.initiator_id = initiator_id
        self.effects: list[dict] = list(effects)
        self.on_done = on_done
        self._selected_index: int | None = None
        self._validation_error: str | None = None
        self._add_options_available = True
        self._rebuild_pick_options()
        self._rebuild_add_options()
        self._update_buttons()

    # --- presentation --------------------------------------------------------

    def _embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Item effects",
            description=(
                "Add typed effects with the buttons below. No JSON needed. "
                "Pick an effect in the list to edit, remove, or move it."
            ),
            color=discord.Color.gold(),
        )
        if not self.effects:
            embed.add_field(name="Effects", value="No effects yet.", inline=False)
        else:
            lines = []
            for index, effect in enumerate(self.effects, start=1):
                marker = "▸" if index - 1 == self._selected_index else " "
                lines.append(f"{marker} {index}. {describe_effect(effect)}")
            embed.add_field(name="Effects", value="\n".join(lines)[:1024], inline=False)
        if len(self.effects) >= STANDARD_MAX_EFFECTS:
            embed.add_field(
                name="Effect limit",
                value=(
                    "This item already has the maximum number of effects allowed "
                    "in the standard editor."
                ),
                inline=False,
            )
        if self._validation_error:
            embed.add_field(name="Validation", value=f"⚠ {self._validation_error}", inline=False)
        embed.set_footer(text=f"{len(self.effects)} effect(s)")
        return embed

    @property
    def message_text(self) -> str:
        return "Assemble the item's effects."

    # --- controls -------------------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "These controls belong to another user.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        """Audit 10.7: a timeout disables controls and tells the admin to restart."""
        for item in self.children:
            item.disabled = True
        count_wizard_timeout("effects_editor")
        if self.message is not None:
            await self.message.edit(content=None, embed=None, view=self)
        self.stop()

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
        self.add_effect.disabled = (
            len(self.effects) >= STANDARD_MAX_EFFECTS or not self._add_options_available
        )

    def _rebuild_add_options(self) -> None:
        options = []
        for option in EFFECT_SELECT_OPTIONS:
            effect_type = str(option.value)
            # Entity-targeted effects may still be added for another target;
            # the final duplicate check runs after their modal is submitted.
            if effect_type in {"grant_item", "loot_table_roll", "stat_add", "stat_multiply"}:
                options.append(option)
            elif not has_duplicate_effect(self.effects, {"type": effect_type}):
                options.append(option)
        self.add_effect.options = options or [
            discord.SelectOption(label="No new effects available", value="-1")
        ]
        self._add_options_available = bool(options)
        self.add_effect.disabled = not options

    @discord.ui.select(
        placeholder="Select an effect to edit/remove/move…",
        min_values=0,
        max_values=1,
    )
    async def pick_effect(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        if select.values and select.values[0] == "-1":
            return
        self._selected_index = int(select.values[0]) if select.values else None
        self._update_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)

    def _rebuild_pick_options(self) -> None:
        if not self.effects:
            # Discord rejects a select without at least one option, so an
            # empty draft shows a disabled placeholder select instead of
            # serializing an options-less component (400 on edit_message).
            self.pick_effect.options = [discord.SelectOption(label="No effects yet", value="-1")]
            self.pick_effect.disabled = True
            self.pick_effect.placeholder = "Add an effect first"
            return
        options = []
        for index, effect in enumerate(self.effects[:25]):
            label = describe_effect(effect)
            options.append(
                discord.SelectOption(
                    label=label[:100] or "effect",
                    value=str(index),
                    description=f"Effect #{index + 1}",
                )
            )
        self.pick_effect.options = options
        self.pick_effect.disabled = False
        self.pick_effect.placeholder = "Select an effect to edit/remove/move…"

    @discord.ui.select(
        placeholder="Add effect…",
        options=EFFECT_SELECT_OPTIONS,
        min_values=1,
        max_values=1,
    )
    async def add_effect(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        effect_type = select.values[0]
        if effect_type == "-1":
            return
        await interaction.response.send_modal(
            modal_for_effect(effect_type, self._on_added, self._refresh_after_save)
        )

    async def _refresh_after_save(self, interaction: discord.Interaction) -> None:
        """Spec §34: after a modal submits, update the editor message in place
        instead of leaving the draft list stale."""
        await interaction.response.edit_message(embed=self._embed(), view=self)

    def _on_added(self, payload: dict) -> None:
        if has_duplicate_effect(self.effects, payload):
            self._validation_error = "Duplicate effect is not allowed."
            self._rebuild_add_options()
            self._update_buttons()
            return
        self.effects.append(payload)
        self._validation_error = None
        self._rebuild_pick_options()
        self._rebuild_add_options()
        self._update_buttons()

    def _replace_effect(self, index: int, payload: dict) -> None:
        if 0 <= index < len(self.effects):
            remaining = self.effects[:index] + self.effects[index + 1 :]
            if has_duplicate_effect(remaining, payload):
                self._validation_error = "Duplicate effect is not allowed."
                self._rebuild_add_options()
                self._update_buttons()
                return
            self.effects[index] = payload
            self._validation_error = None
        self._rebuild_pick_options()
        self._rebuild_add_options()
        self._update_buttons()

    @discord.ui.button(label="Edit selected", style=discord.ButtonStyle.secondary)
    async def edit_selected(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self._selected_index is None:
            return
        effect = self.effects[self._selected_index]
        effect_type = str(effect.get("type") or "")
        selected_index = self._selected_index

        def _on_edited(payload: dict) -> None:
            self._replace_effect(selected_index, payload)

        modal = modal_for_effect(effect_type, _on_edited, self._refresh_after_save)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Remove selected", style=discord.ButtonStyle.danger)
    async def remove_selected(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self._selected_index is None:
            return
        del self.effects[self._selected_index]
        self._selected_index = None
        self._rebuild_pick_options()
        self._rebuild_add_options()
        self._update_buttons()
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Move up", style=discord.ButtonStyle.secondary)
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

    @discord.ui.button(label="Move down", style=discord.ButtonStyle.secondary)
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

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success)
    async def finish_effects(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_done(interaction, list(self.effects))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_effects(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_done(interaction, None)
