from collections.abc import Callable

import discord


class ModalLauncherView(discord.ui.View):
    def __init__(
        self,
        initiator_id: int,
        modal_factory: Callable[[], discord.ui.Modal],
        *,
        label: str = "Open form",
    ):
        super().__init__(timeout=180)
        self.initiator_id = initiator_id
        self.modal_factory = modal_factory
        self.open_form.label = label

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "This form belongs to another user.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Open form", style=discord.ButtonStyle.primary)
    async def open_form(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(self.modal_factory())
