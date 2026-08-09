"""Item template selection step (spec §7/§8)."""

from collections.abc import Awaitable, Callable

import discord

from app.domain.item_ui_registry import ITEM_TEMPLATES
from app.interactions.metrics import count_wizard_timeout

ContinueCallback = Callable[[discord.Interaction, str], Awaitable[None]]
CancelCallback = Callable[[discord.Interaction], Awaitable[None]]


def template_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Create Item",
        description=(
            "Choose the item template that best matches what you want to create. "
            "You can fine-tune the item before saving it."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Templates",
        value="\n".join(f"`{item['label']}`" for item in ITEM_TEMPLATES),
        inline=False,
    )
    embed.set_footer(text="Continue is disabled until a template is selected.")
    return embed


class TemplateSelectView(discord.ui.View):
    """Step 1: pick one of the twelve item templates (spec §7).

    ``Continue`` stays disabled until a template is chosen; ``Cancel`` removes
    the Redis draft and stops the flow (spec §43).
    """

    def __init__(
        self,
        initiator_id: int,
        on_continue: ContinueCallback,
        on_cancel: CancelCallback,
        *,
        timeout: int = 600,
        restart_text: str = "Run /fish item create again.",
    ):
        super().__init__(timeout=timeout)
        self.initiator_id = initiator_id
        self.on_continue = on_continue
        self.on_cancel = on_cancel
        self._restart_text = restart_text
        self._selected: str | None = None
        self.template_select.placeholder = "Select a template…"
        self.template_select.options = [
            discord.SelectOption(
                label=item["label"], value=item["value"], default=(item["value"] == self._selected)
            )
            for item in ITEM_TEMPLATES
        ]
        self.continue_button.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "These controls belong to another user.", ephemeral=True
            )
            return False
        return True

    @discord.ui.select(min_values=0, max_values=1)
    async def template_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        self._selected = select.values[0] if select.values else None
        self.template_select.options = [
            discord.SelectOption(
                label=item["label"], value=item["value"], default=(item["value"] == self._selected)
            )
            for item in ITEM_TEMPLATES
        ]
        self.continue_button.disabled = self._selected is None
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success)
    async def continue_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self._selected is None:
            return
        self.stop()
        await self.on_continue(interaction, self._selected)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.stop()
        await self.on_cancel(interaction)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        count_wizard_timeout("item_template")
        if self.message is not None:
            await self.message.edit(
                content=f"⏱ The template selection expired. {self._restart_text}",
                view=self,
            )
        self.stop()
