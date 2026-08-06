"""Discord /fish events commands (module-per-domain)."""

from typing import Any

import discord
from discord import app_commands

from app.api.errors import EngineError
from app.interactions.launchers import ModalLauncherView
from app.interactions.modals import (
    EventModal,
    MessageTemplateModal,
)
from app.presentation.embeds import (
    event_list_entry,
    placeholder_help_embeds,
)
from app.presentation.formatting import parse_duration
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


def register_events_group(tree, api, sessions, fish) -> None:
        placeholders = app_commands.Group(
            name="placeholders",
            description="View and edit custom message templates",
            parent=fish,
        )

        @placeholders.command(name="list", description="List placeholders for all messages")
        async def placeholders_list(interaction: discord.Interaction) -> None:
            async def operation() -> None:
                result = await api.message_placeholders(interaction)
                embeds = placeholder_help_embeds(result["items"])
                await interaction.followup.send(embeds=embeds, ephemeral=True)

            await _deferred(interaction, operation)

        @placeholders.command(name="show", description="Show one message and its placeholders")
        async def placeholders_show(interaction: discord.Interaction, message_key: str) -> None:
            async def operation() -> None:
                result = await api.message_placeholders(interaction)
                embeds = placeholder_help_embeds(result["items"], message_key)
                await interaction.followup.send(embeds=embeds, ephemeral=True)

            await _deferred(interaction, operation)

        @placeholders.command(name="edit", description="Edit a custom channel message")
        async def placeholders_edit(interaction: discord.Interaction, message_key: str) -> None:
            async def operation() -> None:
                current = await api.messages(interaction)
                normalized_key = message_key.strip().lower()
                item = next(
                    (entry for entry in current["items"] if entry["message_key"] == normalized_key),
                    None,
                )
                if item is None:
                    raise ValueError(f"Unknown message key: {message_key}")

                async def save(
                    modal_interaction: discord.Interaction,
                    template: str | None,
                ) -> None:
                    await _mutation_response(
                        modal_interaction,
                        lambda: api.patch_message(
                            modal_interaction,
                            normalized_key,
                            current["version"],
                            template,
                        ),
                        "Custom message updated." if template else "Custom message reset.",
                    )

                view = ModalLauncherView(
                    interaction.user.id,
                    lambda: MessageTemplateModal(item, save),
                    label="Edit message",
                )
                await interaction.followup.send(
                    f"Editing `{normalized_key}`. Clear the template to restore its default.",
                    view=view,
                    ephemeral=True,
                )

            await _deferred(interaction, operation)

        event = app_commands.Group(name="event", description="Manage channel events", parent=fish)

        @event.command(name="list", description="List configured channel events")
        async def event_list(interaction: discord.Interaction) -> None:
            async def operation() -> None:
                result = await api.events(interaction)
                view = PagedEmbedView(
                    interaction.user.id,
                    "Channel events",
                    result["items"],
                    event_list_entry,
                    page_size=5,
                )
                await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

            await _deferred(interaction, operation)

        @event.command(name="show", description="Show one channel event")
        async def event_show(interaction: discord.Interaction, event_id: int) -> None:
            async def operation() -> None:
                item = await api.event(interaction, event_id)
                await _send_json_embed(interaction, "Event", item)

            await _deferred(interaction, operation)

        @event.command(name="create", description="Create a channel event")
        async def event_create(interaction: discord.Interaction) -> None:
            async def save(modal_interaction: discord.Interaction, payload: dict[str, Any]) -> None:
                await _mutation_response(
                    modal_interaction,
                    lambda: api.create_event(modal_interaction, payload),
                    "Event created.",
                )

            await interaction.response.send_modal(EventModal(save))

        @event.command(name="edit", description="Edit a channel event")
        async def event_edit(interaction: discord.Interaction, event_id: int) -> None:
            async def operation() -> None:
                current = await api.event(interaction, event_id)
                flow_id = await sessions.create(interaction.user.id, current)

                async def save(modal_interaction: discord.Interaction, payload: dict[str, Any]) -> None:
                    async def mutate() -> dict[str, Any]:
                        await _session(sessions, modal_interaction, flow_id)
                        result = await api.patch_event(modal_interaction, event_id, payload)
                        await sessions.delete(modal_interaction.user.id, flow_id)
                        return result

                    await _mutation_response(
                        modal_interaction,
                        mutate,
                        "Event updated.",
                    )

                view = ModalLauncherView(
                    interaction.user.id,
                    lambda: EventModal(save, current),
                )
                await interaction.followup.send("The event form is ready.", view=view, ephemeral=True)

            await _deferred(interaction, operation)

        @event.command(name="start", description="Start an event, optionally for a fixed duration")
        async def event_start(
            interaction: discord.Interaction,
            event_id: int,
            duration: str | None = None,
        ) -> None:
            try:
                current = await api.event(interaction, event_id)
                seconds = parse_duration(duration, maximum=1_209_600) if duration else None
            except (EngineError, ValueError) as error:
                await _send_error(interaction, error)
                return
            await _simple_mutation(
                interaction,
                lambda: api.start_event(interaction, event_id, current["version"], seconds),
                "Event started.",
            )

        @event.command(name="stop", description="Stop the active channel event")
        async def event_stop(interaction: discord.Interaction) -> None:
            await _confirmation(
                interaction,
                "Stop the currently active event?",
                lambda confirmed: api.stop_event(confirmed),
                "Active event stopped.",
                danger=True,
            )

        @event.command(name="delete", description="Delete a channel event")
        async def event_delete(interaction: discord.Interaction, event_id: int) -> None:
            try:
                current = await api.event(interaction, event_id)
            except EngineError as error:
                await _send_error(interaction, error)
                return
            await _confirmation(
                interaction,
                f"Delete event `{event_id}`?",
                lambda confirmed: api.delete_event(confirmed, event_id, current["version"]),
                "Event deleted.",
                danger=True,
            )
        return {
            "placeholders_list": placeholders_list,
            "placeholders_show": placeholders_show,
            "placeholders_edit": placeholders_edit,
            "event_list": event_list,
            "event_show": event_show,
            "event_create": event_create,
            "event_edit": event_edit,
            "event_start": event_start,
            "event_stop": event_stop,
            "event_delete": event_delete,
        }
