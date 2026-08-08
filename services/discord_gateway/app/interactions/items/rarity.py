"""Rarity selection step (spec §10)."""

from collections.abc import Awaitable, Callable

import discord

from app.domain.item_ui_registry import RARITY_OPTIONS
from app.interactions.metrics import count_wizard_timeout

ContinueCallback = Callable[[discord.Interaction, str], Awaitable[None]]
BackCallback = Callable[[discord.Interaction], Awaitable[None]]
CancelCallback = Callable[[discord.Interaction], Awaitable[None]]


def rarity_embed(current: str) -> discord.Embed:
    label = next((name for name, value in RARITY_OPTIONS if value == current), current)
    embed = discord.Embed(
        title="Choose Rarity",
        description=f"Selected rarity: **{label}**.",
        color=discord.Color.blurple(),
    )
    embed.set_footer(text="Rarity affects item-drop luck in the game engine.")
    return embed


class RarityView(discord.ui.View):
    """Step 3: pick common/rare/epic/legendary (spec §10). Defaults to Common."""

    def __init__(
        self,
        initiator_id: int,
        on_continue: ContinueCallback,
        on_back: BackCallback,
        on_cancel: CancelCallback,
        *,
        current: str = "common",
        timeout: int = 600,
        restart_text: str = "Run /fish item create again.",
    ):
        super().__init__(timeout=timeout)
        self.initiator_id = initiator_id
        self.on_continue = on_continue
        self.on_back = on_back
        self.on_cancel = on_cancel
        self._restart_text = restart_text
        self._selected = current
        self.rarity_select.options = [
            discord.SelectOption(label=name, value=value, default=(value == current))
            for name, value in RARITY_OPTIONS
        ]
        # Rarity always has a default (Common), so Continue is available right
        # away; selecting another rarity just updates the embed and the draft.
        self.continue_button.disabled = not bool(current)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "These controls belong to another user.", ephemeral=True
            )
            return False
        return True

    @discord.ui.select(min_values=0, max_values=1)
    async def rarity_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        if select.values:
            self._selected = select.values[0]
        self.continue_button.disabled = False
        await interaction.response.edit_message(embed=rarity_embed(self._selected), view=self)

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success)
    async def continue_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_continue(interaction, self._selected)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_back(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_cancel(interaction)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        count_wizard_timeout("item_rarity")
        if self.message is not None:
            await self.message.edit(
                content=f"⏱ The rarity selection expired. {self._restart_text}",
                view=self,
            )
        self.stop()
