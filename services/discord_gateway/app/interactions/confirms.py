from collections.abc import Awaitable, Callable

import discord


class ConfirmView(discord.ui.View):
    def __init__(
        self,
        initiator_id: int,
        on_confirm: Callable[[discord.Interaction], Awaitable[None]],
        *,
        timeout: float = 120,
        danger: bool = False,
    ):
        super().__init__(timeout=timeout)
        self.initiator_id = initiator_id
        self.on_confirm = on_confirm
        self.confirm.style = discord.ButtonStyle.danger if danger else discord.ButtonStyle.success

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "This confirmation belongs to another user.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await self.on_confirm(interaction)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Operation cancelled.", embed=None, view=self
        )
        self.stop()
