"""Item creation/editing wizard helpers (UI audit §5.1/§9).

The primary item flow builds a draft in memory and lets the admin assemble
effects with the typed effect builder — no raw ``effects_json`` required.
"""

from typing import Any

import discord

from app.interactions.confirms import ConfirmView
from app.interactions.effect_builder import describe_effect
from app.presentation.embeds import item_detail_embed

EQUIPMENT_SLOTS = {"rod", "bait", "defense", "storage", "charm_1", "charm_2"}
VALID_TYPES = {
    "equipment",
    "consumable",
    "lootbox",
    "material",
    "quest",
    "currency",
    "collectible",
}
VALID_RARITIES = {"common", "rare", "epic", "legendary"}


def normalize_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """Normalise type-dependent fields to a valid backend item payload."""
    item_type = draft.get("item_type", "material")
    equipment_slot = draft.get("equipment_slot") if item_type == "equipment" else None
    stack_size = int(draft.get("stack_size", 1))
    if item_type == "equipment":
        stack_size = 1
    break_policy = draft.get("break_policy", "indestructible")
    max_durability = draft.get("max_durability")
    if break_policy == "indestructible":
        max_durability = None
    return {
        "item_id": str(draft.get("item_id", "")).strip().lower(),
        "title": str(draft.get("title", "")).strip(),
        "description": draft.get("description") or None,
        "item_type": item_type,
        "equipment_slot": equipment_slot,
        "rarity": draft.get("rarity", "common"),
        "stack_size": stack_size,
        "max_durability": max_durability,
        "break_policy": break_policy,
        "schema_version": 1,
        "effects": [dict(effect) for effect in (draft.get("effects") or [])],
        "image_url": None,
        "value": None,
    }


def build_item_payload(
    draft: dict[str, Any],
    *,
    expected_version: int | None = None,
    schema_version: int | None = None,
) -> dict[str, Any]:
    """Assemble the backend item mutation payload."""
    payload = normalize_draft(draft)
    if expected_version is not None:
        payload["expected_version"] = expected_version
    if schema_version is not None:
        payload["schema_version"] = schema_version
    return payload


def effects_preview(effects: list[dict[str, Any]]) -> str:
    if not effects:
        return "No effects."
    return "\n".join(f"• {describe_effect(effect)}" for effect in effects)


class ItemPreviewView(ConfirmView):
    """Final confirmation card showing the full human-readable item preview.

    ``on_edit_effects`` (optional) swaps the message to the typed effects
    editor; ``on_cancel`` (optional) cleans up the wizard draft when the admin
    cancels (audit 10.6).
    """

    def __init__(
        self,
        initiator_id: int,
        draft: dict[str, Any],
        on_confirm,
        danger: bool = False,
        on_edit_effects=None,
        on_cancel=None,
    ):
        self.draft = draft
        self.on_edit_effects = on_edit_effects
        self.on_cancel = on_cancel
        super().__init__(initiator_id, on_confirm, danger=danger)
        if on_edit_effects is None:
            self.edit_effects.disabled = True

    def embed(self) -> discord.Embed:
        display = normalize_draft(self.draft)
        embed = item_detail_embed(display)
        embed.add_field(
            name="Effects",
            value=effects_preview(self.draft.get("effects") or [])[:1024],
            inline=False,
        )
        return embed

    @discord.ui.button(
        label="Edit effects",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def edit_effects(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self.on_edit_effects is not None:
            await self.on_edit_effects(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        if self.on_cancel is not None:
            try:
                await self.on_cancel(interaction)
            except Exception:
                pass
        await interaction.response.edit_message(
            content="Operation cancelled.", embed=None, view=self
        )
