"""Discord /fish items commands (module-per-domain)."""


import discord
from discord import app_commands

from app.api.errors import EngineError
from app.interactions.effects_editor import EffectsEditorView
from app.interactions.item_wizard import ItemPreviewView, build_item_payload
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
    _item_payload,
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
        async def item_list(
            interaction: discord.Interaction, include_archived: bool = False
        ) -> None:
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
                await interaction.followup.send(
                    embed=item_detail_embed(result), ephemeral=True
                )

            await _deferred(interaction, operation)

        @item.command(name="create", description="Create a strict typed item definition")
        @app_commands.choices(
            item_type=ITEM_TYPE_CHOICES,
            rarity=RARITY_CHOICES,
            equipment_slot=EQUIPMENT_SLOT_CHOICES,
            break_policy=BREAK_POLICY_CHOICES,
        )
        @app_commands.describe(
            item_id="Stable lowercase ID, for example carbon_rod",
            title="Display name",
            item_type="Item behavior category",
            rarity="Rarity used by item-drop luck",
            equipment_slot="Required only for equipment",
            stack_size="Maximum quantity in one inventory slot; equipment must use 1",
            max_durability="Required for breakable items",
            break_policy="Behavior when durability reaches zero",
            description="Optional item description",
        )
        async def item_create(
            interaction: discord.Interaction,
            item_id: str,
            title: str,
            item_type: app_commands.Choice[str],
            rarity: app_commands.Choice[str],
            equipment_slot: app_commands.Choice[str] | None = None,
            stack_size: app_commands.Range[int, 1, 1_000_000] = 1,
            max_durability: app_commands.Range[int, 1, 1_000_000] | None = None,
            break_policy: app_commands.Choice[str] | None = None,
            description: str | None = None,
        ) -> None:
            async def operation() -> None:
                draft = {
                    "item_id": item_id,
                    "title": title,
                    "item_type": item_type.value,
                    "rarity": rarity.value,
                    "equipment_slot": equipment_slot.value if equipment_slot else None,
                    "stack_size": stack_size,
                    "max_durability": max_durability,
                    "break_policy": break_policy.value if break_policy else "indestructible",
                    "description": description,
                    "effects": [],
                }
                payload = build_item_payload(draft)

                async def confirm(confirmed: discord.Interaction) -> None:
                    await _mutation_response(
                        confirmed,
                        lambda: api.upsert_item(confirmed, payload),
                        "Item created.",
                    )

                view = ItemPreviewView(interaction.user.id, draft, confirm)
                embed = view.embed()
                embed.title = f"Create item: {title}"
                embed.set_footer(text="Effects can be added afterwards with /fish item effect-edit")
                await interaction.edit_original_response(
                    content=None,
                    embed=embed,
                    view=view,
                )

            await _deferred(interaction, operation)

        @item.command(name="edit", description="Replace a versioned typed item definition")
        @app_commands.choices(
            item_type=ITEM_TYPE_CHOICES,
            rarity=RARITY_CHOICES,
            equipment_slot=EQUIPMENT_SLOT_CHOICES,
            break_policy=BREAK_POLICY_CHOICES,
        )
        @app_commands.describe(
            item_id="Existing stable item ID",
            max_durability="Set the new maximum durability",
        )
        async def item_edit(
            interaction: discord.Interaction,
            item_id: str,
            title: str | None = None,
            item_type: app_commands.Choice[str] | None = None,
            rarity: app_commands.Choice[str] | None = None,
            equipment_slot: app_commands.Choice[str] | None = None,
            stack_size: app_commands.Range[int, 1, 1_000_000] | None = None,
            max_durability: app_commands.Range[int, 1, 1_000_000] | None = None,
            break_policy: app_commands.Choice[str] | None = None,
            description: str | None = None,
        ) -> None:
            async def operation() -> None:
                current = await api.item(interaction, item_id)
                resolved_type = item_type.value if item_type else current["item_type"]
                payload = _item_payload(
                    item_id=item_id,
                    title=title or current["title"],
                    item_type=resolved_type,
                    rarity=rarity.value if rarity else current["rarity"],
                    equipment_slot=(
                        equipment_slot.value
                        if equipment_slot
                        else current.get("equipment_slot")
                        if resolved_type == "equipment"
                        else None
                    ),
                    stack_size=stack_size or current["stack_size"],
                    max_durability=(
                        max_durability
                        if max_durability is not None
                        else current.get("max_durability")
                    ),
                    break_policy=(
                        break_policy.value if break_policy else current["break_policy"]
                    ),
                    effects=current["effects"],
                    description=description if description is not None else current.get("description"),
                )
                payload.update(
                    {
                        "expected_version": current["version"],
                        "schema_version": current["schema_version"],
                        "image_url": current.get("image_url"),
                        "value": current.get("value"),
                    }
                )
                await _json_confirmation(
                    interaction,
                    "Item update preview",
                    payload,
                    lambda confirmed: api.upsert_item(confirmed, payload),
                    "Item definition updated.",
                )

            await _deferred(interaction, operation)

        @item.command(name="effect-edit", description="Edit the typed effects of an item without JSON")
        async def item_effect_edit(interaction: discord.Interaction, item_id: str) -> None:
            async def operation() -> None:
                current = await api.item(interaction, item_id)
                current_effects = list(current.get("effects") or [])

                async def on_done(done_interaction, final_effects) -> None:
                    if final_effects is None:
                        await done_interaction.followup.send(
                            "Effect editing cancelled.", ephemeral=True
                        )
                        return
                    payload = _item_payload(
                        item_id=current["item_id"],
                        title=current["title"],
                        item_type=current["item_type"],
                        rarity=current["rarity"],
                        equipment_slot=current.get("equipment_slot"),
                        stack_size=current.get("stack_size", 1),
                        max_durability=current.get("max_durability"),
                        break_policy=current.get("break_policy", "indestructible"),
                        effects=final_effects,
                        description=current.get("description"),
                    )
                    payload.update(
                        {
                            "expected_version": current["version"],
                            "schema_version": current["schema_version"],
                            "image_url": current.get("image_url"),
                            "value": current.get("value"),
                        }
                    )
                    await _json_confirmation(
                        done_interaction,
                        "Item effect update preview",
                        payload,
                        lambda confirmed: api.upsert_item(confirmed, payload),
                        "Item effects updated.",
                    )

                view = EffectsEditorView(
                    interaction.user.id,
                    current_effects,
                    on_done,
                )
                await interaction.followup.send(
                    view.message_text, embed=view._embed(), view=view, ephemeral=True
                )

            await _deferred(interaction, operation)

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
                lambda confirmed: api.archive_item(
                    confirmed, item_id, current["version"]
                ),
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
