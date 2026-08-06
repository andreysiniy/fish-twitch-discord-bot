from collections.abc import Awaitable, Callable
import logging

import discord

from app.api.errors import EngineError, localize_error
from app.interactions.metrics import count_wizard_timeout

logger = logging.getLogger("discord.confirm")


class ConfirmView(discord.ui.View):
    def __init__(
        self,
        initiator_id: int,
        on_confirm: Callable[[discord.Interaction], Awaitable[None]],
        *,
        timeout: float = 180,
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
        if not interaction.response.is_done():
            # Buttons may only ack with DEFERRED_MESSAGE_UPDATE (type 6);
            # discord.py's thinking defer maps to type 5, which Discord
            # rejects, leaving the click unanswered (3s timeout).
            await interaction.response.defer()
        try:
            await self.on_confirm(interaction)
        except (EngineError, ValueError) as error:
            content = localize_error(error) if isinstance(error, EngineError) else str(error)
            await self._report_failure(interaction, content)
        except Exception:
            logger.exception("Confirm callback failed for interaction %s", interaction.id)
            await self._report_failure(
                interaction, "The operation could not be completed."
            )
        finally:
            self.stop()

    async def _report_failure(self, interaction: discord.Interaction, content: str) -> None:
        try:
            await interaction.edit_original_response(
                content=content, embed=None, view=None
            )
        except Exception:
            logger.exception("Failed to report confirm failure")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Operation cancelled.", embed=None, view=self
        )
        self.stop()

    async def on_timeout(self) -> None:
        """Audit §12: a timeout disables controls and tells the admin to restart."""
        for item in self.children:
            item.disabled = True
        message = self.message
        count_wizard_timeout("confirm")
        if message is not None:
            await message.edit(
                content="⏱ Confirmation expired. Run the command again.",
                embed=None,
                view=self,
            )
        self.stop()
