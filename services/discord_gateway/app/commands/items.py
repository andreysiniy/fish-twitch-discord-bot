"""Discord /fish items commands (module-per-domain)."""

import discord
from discord import app_commands

from app.api.errors import EngineError
from app.domain.item_ui_registry import TEMPLATES_BY_VALUE
from app.interactions.items.wizard import (
    start_effect_edit,
    start_item_create,
    start_item_edit,
    template_choices,
)
from app.presentation.embeds import (
    item_detail_embed,
    item_list_entry,
)
from app.presentation.pagination import PagedEmbedView

from app.commands.shared import (  # noqa: F401  (shared helpers)
    BREAK_POLICY_CHOICES,
    EQUIPMENT_SLOT_CHOICES,
    ITEM_TYPE_CHOICES,
    MODIFIER_OPERATION_CHOICES,
    MODIFIER_SCOPE_CHOICES,
    RARITY_CHOICES,
    REWARD_CHOICES,
    SECTION_CHOICES,
    STAT_KEY_CHOICES,
    _confirmation,
    _deferred,
    _error_text,
    _json_confirmation,
    _json_embed,
    _mutation_response,
    _parse_effects,
    _player_modifier_preview_embed,
    _send_error,
    _send_json_embed,
    _session,
    _simple_mutation,
)


def register_items_group(tree, api, sessions, fish) -> None:
    item = app_commands.Group(name="item", description="Manage typed item definitions", parent=fish)

    @item.command(name="list", description="List typed item definitions")
    async def item_list(interaction: discord.Interaction, include_archived: bool = False) -> None:
        async def operation() -> None:
            result = await api.items(interaction, include_archived)
            view = PagedEmbedView(
                interaction.user.id,
                "Item definitions",
                result["items"],
                item_list_entry,
                page_size=8,
            )
            await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

        await _deferred(interaction, operation)

    @item.command(name="show", description="Show every field of one item definition")
    async def item_show(interaction: discord.Interaction, item_id: str) -> None:
        async def operation() -> None:
            result = await api.item(interaction, item_id)
            await interaction.followup.send(embed=item_detail_embed(result), ephemeral=True)

        await _deferred(interaction, operation)

    @item.command(name="create", description="Create a typed item with the step-by-step wizard")
    @app_commands.choices(template=template_choices())
    @app_commands.describe(template="Optional template to prefill the wizard")
    async def item_create(
        interaction: discord.Interaction,
        template: str | None = None,
    ) -> None:
        if template and template not in TEMPLATES_BY_VALUE:
            await interaction.response.send_message(
                "Unknown template. Run /fish item create without arguments.", ephemeral=True
            )
            return
        try:
            await start_item_create(interaction, sessions, api, template=template)
        except (EngineError, ValueError) as error:
            content = _error_text(error)
            if interaction.response.is_done():
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)

    @item.command(name="edit", description="Edit an item definition with the step-by-step wizard")
    @app_commands.describe(item_id="Existing stable item ID")
    async def item_edit(interaction: discord.Interaction, item_id: str) -> None:
        try:
            await start_item_edit(interaction, sessions, api, item_id=item_id)
        except (EngineError, ValueError) as error:
            content = _error_text(error)
            if interaction.response.is_done():
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)

    @item.command(name="effect-edit", description="Edit the typed effects of an item without JSON")
    @app_commands.describe(item_id="Existing stable item ID")
    async def item_effect_edit(interaction: discord.Interaction, item_id: str) -> None:
        try:
            await start_effect_edit(interaction, sessions, api, item_id=item_id)
        except (EngineError, ValueError) as error:
            content = _error_text(error)
            if interaction.response.is_done():
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)

    @item.command(name="archive", description="Archive an item without deleting history")
    async def item_archive(interaction: discord.Interaction, item_id: str) -> None:
        try:
            current = await api.item(interaction, item_id)
        except EngineError as error:
            await _send_error(interaction, error)
            return
        await _confirmation(
            interaction,
            f"Archive item `{item_id}`? Existing inventory rows are preserved.",
            lambda confirmed: api.archive_item(confirmed, item_id, current["version"]),
            "Item archived.",
            danger=True,
        )

    return {
        "item_list": item_list,
        "item_show": item_show,
        "item_create": item_create,
        "item_edit": item_edit,
        "item_effect_edit": item_effect_edit,
        "item_archive": item_archive,
    }
