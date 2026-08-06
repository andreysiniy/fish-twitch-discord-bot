"""Discord /fish rewards commands (module-per-domain)."""

import json
from typing import Any

import discord
from discord import app_commands

from app.api.errors import EngineError
from app.interactions.confirms import ConfirmView
from app.interactions.launchers import ModalLauncherView
from app.interactions.modals import (
    create_reward_modal,
)
from app.presentation.embeds import (
    legacy_import_embed,
    reward_list_entry,
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


def register_rewards_group(tree, api, sessions, fish) -> None:
        reward = app_commands.Group(name="reward", description="Manage location rewards", parent=fish)

        @reward.command(name="list", description="List rewards for a location")
        async def reward_list(interaction: discord.Interaction, location_id: str) -> None:
            async def operation() -> None:
                result = await api.rewards(interaction, location_id)
                view = PagedEmbedView(
                    interaction.user.id,
                    f"Rewards — {location_id}",
                    result["items"],
                    reward_list_entry,
                    page_size=1,
                )
                await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

            await _deferred(interaction, operation)

        @reward.command(name="show", description="Show one reward")
        async def reward_show(
            interaction: discord.Interaction,
            location_id: str,
            reward_id: str,
        ) -> None:
            async def operation() -> None:
                result = await api.rewards(interaction, location_id)
                item = next(
                    (value for value in result["items"] if value["reward_id"] == reward_id), None
                )
                if item is None:
                    raise EngineError(404, "REWARD_NOT_FOUND", "Reward not found")
                await _send_json_embed(interaction, "Reward", item)

            await _deferred(interaction, operation)

        @reward.command(name="add", description="Add a weighted reward to a location")
        @app_commands.choices(reward_type=REWARD_CHOICES)
        async def reward_add(
            interaction: discord.Interaction,
            location_id: str,
            reward_type: app_commands.Choice[str],
        ) -> None:
            async def operation() -> None:
                current = await api.rewards(interaction, location_id)
                flow_id = await sessions.create(interaction.user.id, current)

                async def save(modal_interaction: discord.Interaction, payload: dict[str, Any]) -> None:
                    async def mutate() -> dict[str, Any]:
                        state = await _session(sessions, modal_interaction, flow_id)
                        result = await api.create_reward(
                            modal_interaction, location_id, state["version"], payload
                        )
                        await sessions.delete(modal_interaction.user.id, flow_id)
                        return result

                    await _mutation_response(
                        modal_interaction,
                        mutate,
                        "Reward created.",
                    )

                view = ModalLauncherView(
                    interaction.user.id,
                    lambda: create_reward_modal(reward_type.value, save),
                )
                await interaction.followup.send("The reward form is ready.", view=view, ephemeral=True)

            await _deferred(interaction, operation)

        @reward.command(name="edit", description="Edit a weighted reward")
        async def reward_edit(
            interaction: discord.Interaction,
            location_id: str,
            reward_id: str,
        ) -> None:
            async def operation() -> None:
                current = await api.rewards(interaction, location_id)
                item = next(
                    (value for value in current["items"] if value["reward_id"] == reward_id), None
                )
                if item is None:
                    raise EngineError(404, "REWARD_NOT_FOUND", "Reward not found")
                flow_id = await sessions.create(
                    interaction.user.id,
                    {"version": current["version"], "reward": item},
                )

                async def save(modal_interaction: discord.Interaction, payload: dict[str, Any]) -> None:
                    async def mutate() -> dict[str, Any]:
                        state = await _session(sessions, modal_interaction, flow_id)
                        result = await api.patch_reward(
                            modal_interaction, location_id, reward_id, state["version"], payload
                        )
                        await sessions.delete(modal_interaction.user.id, flow_id)
                        return result

                    await _mutation_response(
                        modal_interaction,
                        mutate,
                        "Reward updated.",
                    )

                view = ModalLauncherView(
                    interaction.user.id,
                    lambda: create_reward_modal(item["type"], save, item),
                )
                await interaction.followup.send("The reward form is ready.", view=view, ephemeral=True)

            await _deferred(interaction, operation)

        @reward.command(name="delete", description="Delete a weighted reward")
        async def reward_delete(
            interaction: discord.Interaction,
            location_id: str,
            reward_id: str,
        ) -> None:
            try:
                current = await api.rewards(interaction, location_id)
            except EngineError as error:
                await _send_error(interaction, error)
                return
            await _confirmation(
                interaction,
                f"Delete reward `{reward_id}` from `{location_id}`?",
                lambda confirmed: api.delete_reward(
                    confirmed, location_id, reward_id, current["version"]
                ),
                "Reward deleted.",
                danger=True,
            )

        @reward.command(name="import-legacy", description="Import rewards from a legacy JSON file")
        async def reward_import_legacy(
            interaction: discord.Interaction,
            location_id: str,
            file: discord.Attachment,
            replace_existing: bool = False,
        ) -> None:
            async def operation() -> None:
                if not file.filename.lower().endswith(".json"):
                    raise ValueError("The uploaded file must use the .json extension.")
                if file.size > 1_048_576:
                    raise ValueError("The legacy reward file must not exceed 1 MiB.")
                raw = await file.read()
                if len(raw) > 1_048_576:
                    raise ValueError("The legacy reward file must not exceed 1 MiB.")
                try:
                    payload = json.loads(raw.decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError("The uploaded file is not valid UTF-8 JSON.") from error
                if not isinstance(payload, dict):
                    raise ValueError("The legacy JSON root must be an object.")

                current = await api.rewards(interaction, location_id)
                preview = await api.import_legacy_rewards(
                    interaction,
                    location_id,
                    current["version"],
                    payload,
                    replace_existing,
                    dry_run=True,
                )

                async def confirm(confirmed: discord.Interaction) -> None:
                    await _mutation_response(
                        confirmed,
                        lambda: api.import_legacy_rewards(
                            confirmed,
                            location_id,
                            current["version"],
                            payload,
                            replace_existing,
                            dry_run=False,
                        ),
                        f"Imported {preview['imported_count']} legacy rewards.",
                    )

                await interaction.followup.send(
                    embed=legacy_import_embed(preview, replace_existing),
                    view=ConfirmView(interaction.user.id, confirm, danger=replace_existing),
                    ephemeral=True,
                )

            await _deferred(interaction, operation)
        return {
            "reward_list": reward_list,
            "reward_show": reward_show,
            "reward_add": reward_add,
            "reward_edit": reward_edit,
            "reward_delete": reward_delete,
            "reward_import_legacy": reward_import_legacy,
        }
