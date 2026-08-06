"""Discord /fish item_drops commands (module-per-domain)."""


import discord
from discord import app_commands

from app.api.errors import EngineError
from app.interactions.confirms import ConfirmView
from app.presentation.embeds import (
    item_drop_list_entry,
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
                probability = preview.get("drop_probability", 0.0)
                expected = preview.get("expected_casts_to_drop")

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

                embed = discord.Embed(
                    title=f"Add item drop: {item_id}",
                    description=f"Location `{location_id}` · weight `{weight}`",
                    color=discord.Color.orange(),
                )
                embed.add_field(
                    name="Drop chance",
                    value=(
                        f"{probability * 100:.2f}% per cast"
                        + (f" (≈{expected} casts)" if expected is not None else "")
                    ),
                    inline=False,
                )
                embed.add_field(
                    name="Details",
                    value=(
                        f"XP: {xp_gain}\n"
                        f"Stock: {'unlimited' if quantity is None else quantity}\n"
                        f"Message: {message}"
                    ),
                    inline=False,
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
                # casts, XP, stock and message (audit 10.11).
                preview = await api.preview_item_drop(
                    interaction, location_id, payload["weight"]
                )
                probability = preview.get("drop_probability", 0.0)
                expected = preview.get("expected_casts_to_drop")

                async def confirm(confirmed: discord.Interaction) -> None:
                    await _mutation_response(
                        confirmed,
                        lambda: api.upsert_item_drop(
                            confirmed, location_id, payload
                        ),
                        "Item drop updated.",
                    )

                embed = discord.Embed(
                    title=f"Edit item drop: {item_id}",
                    description=f"Location `{location_id}` · weight `{payload['weight']}`",
                    color=discord.Color.orange(),
                )
                embed.add_field(name="Chance per cast", value=f"{float(probability):.2%}")
                if expected is not None:
                    embed.add_field(name="Expected casts to drop", value=str(expected))
                embed.add_field(name="XP", value=str(payload["xp_gain"]))
                embed.add_field(
                    name="Stock",
                    value="unlimited"
                    if payload["quantity"] is None
                    else str(payload["quantity"]),
                )
                embed.add_field(name="Message", value=str(payload["message"] or "")[:200])
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
