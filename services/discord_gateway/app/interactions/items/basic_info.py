"""Basic Information step (spec §9)."""

from collections.abc import Awaitable, Callable

import discord

from app.domain.item_ui_registry import slugify_item_id, validate_item_id

SubmitCallback = Callable[[discord.Interaction, dict], Awaitable[None]]


class BasicInfoModal(discord.ui.Modal):
    """Step 2: display name, stable item ID, description (spec §9).

    The stable item ID is optional: when left blank the gateway derives it from
    the display name (``Storm Rod`` → ``storm_rod``). If a valid ID cannot be
    derived automatically, the wizard asks the admin to enter one manually.
    """

    def __init__(self, on_submit: SubmitCallback, *, current: dict | None = None):
        super().__init__(title="Basic Information")
        # Kept off the ``on_submit`` name so discord.py's modal submit dispatch
        # (which calls ``modal.on_submit(interaction)``) is not shadowed.
        self._on_submit = on_submit
        current = current or {}
        self.display_name = discord.ui.TextInput(
            label="Display Name",
            max_length=120,
            required=True,
            default=current.get("title") or "",
        )
        self.item_id = discord.ui.TextInput(
            label="Stable Item ID",
            max_length=120,
            required=False,
            placeholder="storm_rod",
            default=current.get("item_id") or "",
        )
        self.description = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=False,
            default=current.get("description") or "",
        )
        for field in (self.display_name, self.item_id, self.description):
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        title = self.display_name.value.strip()
        if not title or len(title) > 120:
            await self._fail(interaction, "Display name must be 1..120 characters.")
            return
        manual_id = self.item_id.value.strip()
        if manual_id:
            if not validate_item_id(manual_id):
                await self._fail(
                    interaction,
                    "Invalid Stable Item ID. Use lowercase letters, digits, `_` or `-` "
                    "and start with a letter or digit.",
                )
                return
            item_id = manual_id.lower()
        else:
            item_id = slugify_item_id(title)
            if item_id is None:
                await self._fail(
                    interaction,
                    "Could not build a stable item ID from the display name automatically. "
                    "Enter it manually.",
                )
                return
        description = self.description.value.strip() or None
        await self._on_submit(
            interaction,
            {"title": title, "item_id": item_id, "description": description},
        )

    async def _fail(self, interaction: discord.Interaction, message: str) -> None:
        await interaction.response.send_message(message, ephemeral=True)
