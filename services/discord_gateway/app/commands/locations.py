"""Discord /fish locations commands (module-per-domain)."""

from typing import Any

import discord
from discord import app_commands

from app.interactions.launchers import ModalLauncherView
from app.interactions.modals import (
    LocationModal,
)
from app.presentation.embeds import (
    location_detail_embed,
    location_list_entry,
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


def register_locations_group(tree, api, sessions, fish) -> None:
        location = app_commands.Group(
            name="location", description="Manage fishing locations", parent=fish
        )

        @location.command(name="list", description="List configured fishing locations")
        async def location_list(interaction: discord.Interaction) -> None:
            async def operation() -> None:
                result = await api.locations(interaction)
                view = PagedEmbedView(
                    interaction.user.id,
                    "Fishing locations",
                    result["items"],
                    location_list_entry,
                )
                await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

            await _deferred(interaction, operation)

        @location.command(name="show", description="Show one fishing location")
        async def location_show(interaction: discord.Interaction, location_id: str) -> None:
            async def operation() -> None:
                item = await api.location(interaction, location_id)
                await interaction.followup.send(
                    embed=location_detail_embed(item), ephemeral=True
                )

            await _deferred(interaction, operation)

        @location.command(name="create", description="Create a fishing location")
        async def location_create(interaction: discord.Interaction) -> None:
            async def save(modal_interaction: discord.Interaction, payload: dict[str, Any]) -> None:
                await _mutation_response(
                    modal_interaction,
                    lambda: api.create_location(modal_interaction, payload),
                    "Location created.",
                )

            await interaction.response.send_modal(LocationModal(save))

        @location.command(name="edit", description="Edit a fishing location")
        async def location_edit(interaction: discord.Interaction, location_id: str) -> None:
            async def operation() -> None:
                current = await api.location(interaction, location_id)
                flow_id = await sessions.create(interaction.user.id, current)

                async def save(modal_interaction: discord.Interaction, payload: dict[str, Any]) -> None:
                    async def mutate() -> dict[str, Any]:
                        await _session(sessions, modal_interaction, flow_id)
                        result = await api.patch_location(modal_interaction, location_id, payload)
                        await sessions.delete(modal_interaction.user.id, flow_id)
                        return result

                    await _mutation_response(
                        modal_interaction,
                        mutate,
                        "Location updated.",
                    )

                view = ModalLauncherView(
                    interaction.user.id,
                    lambda: LocationModal(save, current),
                )
                await interaction.followup.send(
                    "The location form is ready.", view=view, ephemeral=True
                )

            await _deferred(interaction, operation)

        @location.command(name="delete", description="Delete a fishing location")
        async def location_delete(interaction: discord.Interaction, location_id: str) -> None:
            await _confirmation(
                interaction,
                f"Delete location `{location_id}` and all of its rewards?",
                lambda confirmed: api.delete_location(confirmed, location_id),
                "Location deleted.",
                danger=True,
            )
        return {
            "location_list": location_list,
            "location_show": location_show,
            "location_create": location_create,
            "location_edit": location_edit,
            "location_delete": location_delete,
        }
