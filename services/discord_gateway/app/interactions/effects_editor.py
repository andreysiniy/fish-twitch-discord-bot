"""Editing view for a draft item effect list (no raw JSON in the primary UI)."""

import discord

from app.interactions.effect_builder import (
    EFFECT_SELECT_OPTIONS,
    describe_effect,
    modal_for_effect,
)


class EffectsEditorView(discord.ui.View):
    """Lets an admin assemble the typed effects list for an item draft.

    The draft effects are stored in the wizard session by the caller; this view
    only mutates the list in memory and returns the finished list via ``on_done``.
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
        self._update_buttons()

    # --- presentation --------------------------------------------------------

    def _embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Item effects",
            description=(
                "Add typed effects with the buttons below. No JSON needed."
            ),
            color=discord.Color.gold(),
        )
        if not self.effects:
            embed.add_field(name="Effects", value="No effects yet.", inline=False)
        else:
            text = "\n".join(
                f"{index}. {describe_effect(effect)}"
                for index, effect in enumerate(self.effects, start=1)
            )
            embed.add_field(name="Effects", value=text[:1024], inline=False)
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

    def _update_buttons(self) -> None:
        self.remove_effect.disabled = not self.effects
        self.add_effect.disabled = len(self.effects) >= 50
        self.finish_effects.disabled = not self.effects

    @discord.ui.select(
        placeholder="Add effect…",
        options=EFFECT_SELECT_OPTIONS,
        min_values=1,
        max_values=1,
    )
    async def add_effect(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        effect_type = select.values[0]
        await interaction.response.send_modal(modal_for_effect(effect_type, self._on_added))

    def _on_added(self, payload: dict) -> None:
        self.effects.append(payload)
        self._update_buttons()

    @discord.ui.button(label="Remove last", style=discord.ButtonStyle.secondary)
    async def remove_effect(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self.effects:
            self.effects.pop()
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
