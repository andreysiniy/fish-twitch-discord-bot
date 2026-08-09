"""Discord /fish item_drops commands (module-per-domain)."""


import discord
from discord import app_commands

from app.api.errors import EngineError
from app.interactions.confirms import ConfirmView
from app.presentation.embeds import (
    item_drop_list_entry,
    item_drop_preview_embed,
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
            quantity="Finite channel stock; omit for unlimited stock",
            weight="Relative item selection weight",
            xp_gain="Extra XP awarded with this item",
            message="Chat message; {name} is the item title",
        )
        async def item_drop_add(
            interaction: discord.Interaction,
            location_id: str,
            item_id: str,
            weight: app_commands.Range[int, 1, 1_000_000] = 100,
            xp_gain: app_commands.Range[int, 0, 1_000_000] = 0,
            quantity: app_commands.Range[int, 0, 1_000_000_000] | None = None,
            message: str = "You caught {name}!",
        ) -> None:
            async def operation() -> None:
                preview = await api.preview_item_drop(interaction, location_id, weight)

                async def confirm(confirmed: discord.Interaction) -> None:
                    await _mutation_response(
                        confirmed,
                        lambda: api.upsert_item_drop(
                            confirmed,
                            location_id,
                            {
                                "item_id": item_id,
                                "weight": weight,
                                "xp_gain": xp_gain,
                                "quantity": quantity,
                                "message": message,
                            },
                        ),
                        "Item drop added.",
                    )

                embed = item_drop_preview_embed(
                    action="Add",
                    location_id=location_id,
                    preview=preview,
                    payload={
                        "item_id": item_id,
                        "weight": weight,
                        "xp_gain": xp_gain,
                        "quantity": quantity,
                        "message": message,
                    },
                )
                await interaction.edit_original_response(
                    content=None, embed=embed, view=ConfirmView(interaction.user.id, confirm)
                )

            await _deferred(interaction, operation)

        @item_drop.command(name="edit", description="Edit a versioned item drop")
        @app_commands.describe(
            unlimited_stock="Set true to remove the finite stock limit",
            quantity="New finite stock; omit to preserve the current value",
        )
        async def item_drop_edit(
            interaction: discord.Interaction,
            location_id: str,
            item_id: str,
            weight: app_commands.Range[int, 1, 1_000_000] | None = None,
            xp_gain: app_commands.Range[int, 0, 1_000_000] | None = None,
            quantity: app_commands.Range[int, 0, 1_000_000_000] | None = None,
            message: str | None = None,
            unlimited_stock: bool = False,
        ) -> None:
            async def operation() -> None:
                current = await api.item_drops(interaction, location_id)
                row = next(
                    (entry for entry in current["items"] if entry["item_id"] == item_id),
                    None,
                )
                if not row:
                    raise EngineError(404, "ITEM_DROP_NOT_FOUND", "Item drop not found in this channel")
                payload = {
                    "item_id": item_id,
                    "weight": weight if weight is not None else row["weight"],
                    "xp_gain": xp_gain if xp_gain is not None else row["xp_gain"],
                    "quantity": (
                        None
                        if unlimited_stock
                        else quantity if quantity is not None else row["quantity"]
                    ),
                    "message": message if message is not None else row["message"],
                    "expected_version": row["version"],
                }
                # Same calculated preview as add: chance per cast, expected
                # casts, active time, p50/p90, XP, stock, message and the diff
                # vs the current configuration (audit 10.11, §10).
                preview = await api.preview_item_drop(
                    interaction, location_id, payload["weight"], item_id=item_id
                )

                async def confirm(confirmed: discord.Interaction) -> None:
                    await _mutation_response(
                        confirmed,
                        lambda: api.upsert_item_drop(
                            confirmed, location_id, payload
                        ),
                        "Item drop updated.",
                    )

                embed = item_drop_preview_embed(
                    action="Edit",
                    location_id=location_id,
                    preview=preview,
                    payload=payload,
                    current=row,
                )
                view = ConfirmView(
                    interaction.user.id,
                    confirm,
                )
                await interaction.edit_original_response(
                    content=None,
                    embed=embed,
                    view=view,
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
