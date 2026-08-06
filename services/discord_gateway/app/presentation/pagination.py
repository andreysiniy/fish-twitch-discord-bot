from collections.abc import Callable, Sequence
from typing import Any

import discord

from app.interactions.metrics import count_wizard_timeout


class PagedEmbedView(discord.ui.View):
    def __init__(
        self,
        initiator_id: int,
        title: str,
        items: Sequence[dict[str, Any]],
        formatter: Callable[[dict[str, Any]], tuple[str, str]] | None = None,
        *,
        page_size: int = 10,
        embed_builder: Callable[[dict[str, Any]], discord.Embed] | None = None,
    ):
        super().__init__(timeout=600)
        if embed_builder is None and formatter is None:
            raise ValueError("PagedEmbedView requires formatter or embed_builder")
        self.initiator_id = initiator_id
        self.title = title
        self.items = list(items)
        self.formatter = formatter
        self.embed_builder = embed_builder
        # Rich detail views render one entry per page.
        self.page_size = 1 if embed_builder is not None else page_size
        self.page = 0
        self._update_buttons()

    @property
    def page_count(self) -> int:
        return max(1, (len(self.items) + self.page_size - 1) // self.page_size)

    def embed(self) -> discord.Embed:
        start = self.page * self.page_size
        page_items = self.items[start : start + self.page_size]
        if self.embed_builder is not None:
            embed = (
                self.embed_builder(page_items[0])
                if page_items
                else discord.Embed(
                    title=self.title, description="No entries.",
                    color=discord.Color.blurple(),
                )
            )
            embed.set_footer(
                text=f"Page {self.page + 1}/{self.page_count} • {len(self.items)} entries"
            )
            return embed
        embed = discord.Embed(title=self.title, color=discord.Color.blurple())
        if not page_items:
            embed.description = "No entries."
        assert self.formatter is not None
        for item in page_items:
            name, value = self.formatter(item)
            chunks = _field_chunks(value)
            for index, chunk in enumerate(chunks):
                field_name = name if index == 0 else f"{name} (continued)"
                embed.add_field(name=field_name[:256], value=chunk, inline=False)
        embed.set_footer(text=f"Page {self.page + 1}/{self.page_count} • {len(self.items)} entries")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.initiator_id:
            await interaction.response.send_message(
                "These controls belong to another user.", ephemeral=True
            )
            return False
        return True

    def _update_buttons(self) -> None:
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page >= self.page_count - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = min(self.page_count - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embed(), view=self)


    async def on_timeout(self) -> None:
        """Audit 10.7: a timeout disables controls and tells the admin to restart."""
        for item in self.children:
            item.disabled = True
        count_wizard_timeout("pagination")
        if self.message is not None:
            await self.message.edit(content=None, view=self)
        self.stop()


def _field_chunks(value: str, limit: int = 1024) -> list[str]:
    if not value:
        return ["—"]
    chunks = []
    remaining = value
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit + 1)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    return chunks
