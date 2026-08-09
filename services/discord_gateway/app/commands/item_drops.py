"""Discord /fish item_drops commands (module-per-domain)."""


import discord
from discord import app_commands

from app.api.errors import EngineError
from app.interactions.launchers import ModalLauncherView
from app.interactions.modals import ItemDropModal
from app.presentation.embeds import item_drop_list_entry
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


def register_item_drops_group(tree, api, sessions, fish) -> None:
        item_drop = app_commands.Group(
            name="item-drop", description="Manage location item drops", parent=fish
        )

        @item_drop.command(name="list", description="List item drops for a location")
        async def item_drop_list(interaction: discord.Interaction, location_id: str) -> None:
            async def operation() -> None:
                result = await api.item_drops(interaction, location_id)
                view = PagedEmbedView(
                    interaction.user.id,
                    f"Item drops — {location_id}",
                    result["items"],
                    item_drop_list_entry,
                    page_size=10,
                )
                await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

            await _deferred(interaction, operation)

        @item_drop.command(name="add", description="Add an item drop to a location")
        @app_commands.describe(
            location_id="Location that drops the item",
            item_id="Item to add to the location drops",
        )
        async def item_drop_add(
            interaction: discord.Interaction,
            location_id: str,
            item_id: str,
        ) -> None:
            async def save(
                modal_interaction: discord.Interaction, payload: dict
            ) -> None:
                await _mutation_response(
                    modal_interaction,
                    lambda: api.upsert_item_drop(modal_interaction, location_id, payload),
                    "Item drop added.",
                )

            async def previewer(
                modal_interaction: discord.Interaction, payload: dict
            ) -> dict:
                return await api.preview_item_drop(
                    modal_interaction, location_id, payload["weight"]
                )

            await interaction.response.send_modal(
                ItemDropModal(
                    on_save=save,
                    previewer=previewer,
                    location_id=location_id,
                    item_id=item_id,
                    action="Add",
                )
            )

        @item_drop.command(name="edit", description="Edit a versioned item drop")
        @app_commands.describe(
            location_id="Location with the item drop",
            item_id="Item whose drop to edit",
        )
        async def item_drop_edit(
            interaction: discord.Interaction,
            location_id: str,
            item_id: str,
        ) -> None:
            async def operation() -> None:
                current = await api.item_drops(interaction, location_id)
                row = next(
                    (entry for entry in current["items"] if entry["item_id"] == item_id),
                    None,
                )
                if not row:
                    raise EngineError(404, "ITEM_DROP_NOT_FOUND", "Item drop not found in this channel")

                async def save(
                    modal_interaction: discord.Interaction, payload: dict
                ) -> None:
                    await _mutation_response(
                        modal_interaction,
                        lambda: api.upsert_item_drop(
                            modal_interaction,
                            location_id,
                            {**payload, "expected_version": row["version"]},
                        ),
                        "Item drop updated.",
                    )

                async def previewer(
                    modal_interaction: discord.Interaction, payload: dict
                ) -> dict:
                    return await api.preview_item_drop(
                        modal_interaction,
                        location_id,
                        payload["weight"],
                        item_id=item_id,
                    )

                view = ModalLauncherView(
                    interaction.user.id,
                    lambda: ItemDropModal(
                        on_save=save,
                        previewer=previewer,
                        location_id=location_id,
                        item_id=item_id,
                        action="Edit",
                        defaults=row,
                    ),
                )
                await interaction.followup.send(
                    "The item drop form is ready.", view=view, ephemeral=True
                )

            await _deferred(interaction, operation)

        @item_drop.command(name="remove", description="Remove an item drop from a location")
        async def item_drop_remove(
            interaction: discord.Interaction, location_id: str, item_id: str
        ) -> None:
            try:
                current = await api.item_drops(interaction, location_id)
                row = next(
                    (entry for entry in current["items"] if entry["item_id"] == item_id),
                    None,
                )
                if not row:
                    raise EngineError(404, "ITEM_DROP_NOT_FOUND", "Item drop not found in this channel")
            except (EngineError, ValueError) as error:
                await _send_error(interaction, error)
                return
            await _confirmation(
                interaction,
                f"Remove item `{item_id}` from location `{location_id}`?",
                lambda confirmed: api.remove_item_drop(
                    confirmed, location_id, item_id, row["version"]
                ),
                "Item drop removed.",
                danger=True,
            )
        return {
            "item_drop_list": item_drop_list,
            "item_drop_add": item_drop_add,
            "item_drop_edit": item_drop_edit,
            "item_drop_remove": item_drop_remove,
        }
