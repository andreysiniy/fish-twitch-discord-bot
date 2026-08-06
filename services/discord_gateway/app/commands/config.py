"""Discord /fish config commands (module-per-domain)."""

from typing import Any

import discord
from discord import app_commands

from app.api.errors import EngineError
from app.interactions.launchers import ModalLauncherView
from app.interactions.modals import (
    ConfigModal,
)
from app.presentation.embeds import (
    config_embed,
)
from app.presentation.formatting import parse_duration

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


def register_config_group(tree, api, sessions, fish) -> None:
        config = app_commands.Group(name="config", description="Manage game configuration", parent=fish)

        @config.command(name="show", description="Show effective game configuration")
        @app_commands.choices(section=SECTION_CHOICES)
        async def config_show(
            interaction: discord.Interaction,
            section: app_commands.Choice[str] | None = None,
        ) -> None:
            async def operation() -> None:
                result = await api.config(interaction)
                selected = section.value if section else None
                if selected:
                    schema = await api.config_schema(interaction)
                    keys = schema["sections"][selected]["fields"]
                    result = {
                        **result,
                        "effective": {k: v for k, v in result["effective"].items() if k in keys},
                    }
                await interaction.followup.send(embed=config_embed(result, selected), ephemeral=True)

            await _deferred(interaction, operation)

        @config.command(name="edit", description="Edit a configuration section")
        @app_commands.choices(section=SECTION_CHOICES)
        async def config_edit(
            interaction: discord.Interaction,
            section: app_commands.Choice[str],
        ) -> None:
            async def operation() -> None:
                current = await api.config(interaction)
                schema = await api.config_schema(interaction)
                flow_id = await sessions.create(interaction.user.id, current)

                async def save(modal_interaction: discord.Interaction, changes: dict[str, Any]) -> None:
                    async def mutate() -> dict[str, Any]:
                        state = await _session(sessions, modal_interaction, flow_id)
                        result = await api.patch_config(modal_interaction, state["version"], changes)
                        await sessions.delete(modal_interaction.user.id, flow_id)
                        return result

                    await _mutation_response(
                        modal_interaction,
                        mutate,
                        "Configuration updated.",
                    )

                view = ModalLauncherView(
                    interaction.user.id,
                    lambda: ConfigModal(section.value, current["effective"], schema, save),
                )
                await interaction.followup.send(
                    "The settings form is ready.", view=view, ephemeral=True
                )

            await _deferred(interaction, operation)

        @config.command(name="reset", description="Reset one configuration section to defaults")
        @app_commands.choices(section=SECTION_CHOICES)
        async def config_reset(
            interaction: discord.Interaction,
            section: app_commands.Choice[str],
        ) -> None:
            try:
                current = await api.config(interaction)
            except EngineError as error:
                await _send_error(interaction, error)
                return
            await _confirmation(
                interaction,
                f"Reset the {section.value} section to defaults?",
                lambda confirmed: api.reset_config(confirmed, current["version"], section.value),
                "Configuration section reset.",
                danger=True,
            )

        @config.command(name="cooldown", description="Set normal and subscriber fishing cooldowns")
        async def config_cooldown(
            interaction: discord.Interaction,
            normal: str,
            subscriber: str,
        ) -> None:
            try:
                changes = {
                    "fishing_cooldown": parse_duration(normal, maximum=86_400),
                    "subs_fishing_cooldown": parse_duration(subscriber, maximum=86_400),
                }
                current = await api.config(interaction)
            except (EngineError, ValueError) as error:
                await _send_error(interaction, error)
                return
            await _simple_mutation(
                interaction,
                lambda: api.patch_config(interaction, current["version"], changes),
                "Cooldown settings updated.",
            )
        return {
            "config_show": config_show,
            "config_edit": config_edit,
            "config_reset": config_reset,
            "config_cooldown": config_cooldown,
        }
