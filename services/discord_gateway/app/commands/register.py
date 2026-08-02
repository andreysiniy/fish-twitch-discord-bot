import json
from typing import Any

import discord
from discord import app_commands

from app.api.admin import AdminApi
from app.api.errors import EngineError, localize_error
from app.interactions.confirms import ConfirmView
from app.interactions.launchers import ModalLauncherView
from app.interactions.modals import ConfigModal, EventModal, LocationModal, create_reward_modal
from app.interactions.sessions import WizardSessionStore
from app.presentation.embeds import (
    config_embed,
    event_list_entry,
    location_list_entry,
    placeholder_help_embeds,
    reward_list_entry,
    status_embed,
)
from app.presentation.formatting import parse_duration
from app.presentation.pagination import PagedEmbedView

SECTION_CHOICES = [
    app_commands.Choice(name=value.title(), value=value)
    for value in ("xp", "economy", "robbery", "cooldown")
]
REWARD_CHOICES = [
    app_commands.Choice(name=value.replace("_", " ").title(), value=value)
    for value in ("fish", "timeout", "robbery", "russian_roulette", "nothing")
]


def register_commands(
    tree: app_commands.CommandTree,
    api: AdminApi,
    sessions: WizardSessionStore,
) -> None:
    fish = app_commands.Group(name="fish", description="Manage Fisher Bot")
    account = app_commands.Group(name="account", description="Manage your Twitch link", parent=fish)
    setup = app_commands.Group(name="setup", description="Bind this Discord server", parent=fish)
    config = app_commands.Group(name="config", description="Manage game configuration", parent=fish)
    location = app_commands.Group(
        name="location", description="Manage fishing locations", parent=fish
    )
    reward = app_commands.Group(name="reward", description="Manage location rewards", parent=fish)
    event = app_commands.Group(name="event", description="Manage channel events", parent=fish)

    @fish.command(name="help", description="Show available Fisher Bot commands")
    async def help_command(interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="Fisher Bot administration", color=discord.Color.blurple())
        embed.description = (
            "Use `/fish account link` first, then `/fish setup bind` in the server you manage.\n\n"
            "`account` — Twitch identity link\n"
            "`setup` — server-to-channel binding\n"
            "`config` — XP, economy, robbery, and cooldown settings\n"
            "`location` — fishing locations\n"
            "`reward` — weighted channel rewards\n"
            "`event` — channel events\n"
            "`placeholders` — message placeholder reference"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @fish.command(name="placeholders", description="Show placeholders for custom messages")
    async def placeholders(
        interaction: discord.Interaction,
        message_key: str | None = None,
    ) -> None:
        async def operation() -> None:
            result = await api.message_placeholders(interaction)
            try:
                embeds = placeholder_help_embeds(result["items"], message_key)
            except ValueError as error:
                await interaction.followup.send(str(error), ephemeral=True)
                return
            await interaction.followup.send(embeds=embeds, ephemeral=True)

        await _deferred(interaction, operation)

    @account.command(name="link", description="Create a one-time Twitch authorization link")
    async def account_link(interaction: discord.Interaction) -> None:
        async def operation() -> None:
            result = await api.link_start(interaction)
            view = discord.ui.View(timeout=600)
            view.add_item(
                discord.ui.Button(label="Authorize on Twitch", url=result["authorization_url"])
            )
            await interaction.followup.send(
                "Open the authorization page. This link expires in 10 minutes.",
                view=view,
                ephemeral=True,
            )

        await _deferred(interaction, operation)

    @account.command(name="status", description="Show your Twitch link and server binding")
    async def account_status(interaction: discord.Interaction) -> None:
        async def operation() -> None:
            result = await api.status(interaction)
            await interaction.followup.send(embed=status_embed(result), ephemeral=True)

        await _deferred(interaction, operation)

    @account.command(name="unlink", description="Remove your Twitch account link")
    async def account_unlink(interaction: discord.Interaction) -> None:
        await _confirmation(
            interaction,
            "Unlink your Twitch account? Server settings will remain unchanged.",
            lambda confirmed: api.unlink(confirmed),
            "Twitch account unlinked.",
            danger=True,
        )

    @fish.command(name="link", description="Create a one-time Twitch authorization link")
    async def quick_link(interaction: discord.Interaction) -> None:
        await account_link.callback(interaction)

    @fish.command(name="status", description="Show your Twitch link and server binding")
    async def quick_status(interaction: discord.Interaction) -> None:
        await account_status.callback(interaction)

    @fish.command(name="unlink", description="Remove your Twitch account link")
    async def quick_unlink(interaction: discord.Interaction) -> None:
        await account_unlink.callback(interaction)

    @setup.command(name="status", description="Show the current server binding")
    async def setup_status(interaction: discord.Interaction) -> None:
        await account_status.callback(interaction)

    @setup.command(name="bind", description="Bind this server to your Twitch channel")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def setup_bind(interaction: discord.Interaction) -> None:
        await _simple_mutation(interaction, lambda: api.setup(interaction), "Server binding saved.")

    @setup.command(name="replace", description="Replace the existing server binding")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def setup_replace(interaction: discord.Interaction) -> None:
        await _confirmation(
            interaction,
            "Replace this server's Twitch channel binding?",
            lambda confirmed: api.setup(confirmed, replace=True),
            "Server binding replaced.",
            danger=True,
        )

    @setup.command(name="remove", description="Remove the server binding")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def setup_remove(interaction: discord.Interaction) -> None:
        await _confirmation(
            interaction,
            "Remove this server's Twitch channel binding?",
            lambda confirmed: api.setup_remove(confirmed),
            "Server binding removed.",
            danger=True,
        )

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
            await interaction.followup.send(embed=_json_embed("Location", item), ephemeral=True)

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
            await interaction.followup.send(embed=_json_embed("Reward", item), ephemeral=True)

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
            await interaction.followup.send(embed=_json_embed("Event", item), ephemeral=True)

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

    async def location_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        try:
            result = await api.locations(interaction)
        except EngineError:
            return []
        needle = current.casefold()
        return [
            app_commands.Choice(
                name=f"{item['location_name']} ({item['location_id']})"[:100],
                value=item["location_id"],
            )
            for item in result["items"]
            if needle in item["location_id"].casefold()
            or needle in item["location_name"].casefold()
        ][:25]

    async def reward_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        location_id = getattr(interaction.namespace, "location_id", None)
        if not location_id:
            return []
        try:
            result = await api.rewards(interaction, location_id)
        except EngineError:
            return []
        needle = current.casefold()
        return [
            app_commands.Choice(
                name=f"{item.get('name') or item['type']} ({item['reward_id']})"[:100],
                value=item["reward_id"],
            )
            for item in result["items"]
            if needle in item["reward_id"].casefold()
            or needle in str(item.get("name") or item["type"]).casefold()
        ][:25]

    async def event_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[int]]:
        try:
            result = await api.events(interaction)
        except EngineError:
            return []
        needle = current.casefold()
        return [
            app_commands.Choice(
                name=f"{item['event_title']} ({item['id']})"[:100],
                value=int(item["id"]),
            )
            for item in result["items"]
            if needle in str(item["id"]).casefold() or needle in item["event_title"].casefold()
        ][:25]

    for command in (location_show, location_edit, location_delete, reward_list, reward_add):
        command.autocomplete("location_id")(location_autocomplete)
    for command in (reward_show, reward_edit, reward_delete):
        command.autocomplete("location_id")(location_autocomplete)
        command.autocomplete("reward_id")(reward_autocomplete)
    for command in (event_show, event_edit, event_start, event_delete):
        command.autocomplete("event_id")(event_autocomplete)

    tree.add_command(fish)


async def _deferred(interaction: discord.Interaction, operation) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        await operation()
    except (EngineError, ValueError) as error:
        await _send_error(interaction, error)


async def _simple_mutation(interaction, operation, success: str) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        await operation()
        await interaction.followup.send(success, ephemeral=True)
    except (EngineError, ValueError) as error:
        await _send_error(interaction, error)


async def _mutation_response(interaction, operation, success: str) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        await operation()
        await interaction.edit_original_response(content=success, embed=None, view=None)
    except (EngineError, ValueError) as error:
        await interaction.edit_original_response(content=_error_text(error), embed=None, view=None)


async def _confirmation(interaction, prompt, operation, success, *, danger=False) -> None:
    async def confirm(confirmed: discord.Interaction) -> None:
        await _mutation_response(confirmed, lambda: operation(confirmed), success)

    await interaction.response.send_message(
        prompt,
        view=ConfirmView(interaction.user.id, confirm, danger=danger),
        ephemeral=True,
    )


async def _send_error(interaction: discord.Interaction, error: Exception) -> None:
    content = _error_text(error)
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


def _error_text(error: Exception) -> str:
    if isinstance(error, EngineError):
        return localize_error(error)
    return str(error) or "The operation could not be completed."


def _json_embed(title: str, item: dict[str, Any]) -> discord.Embed:
    rendered = json.dumps(item, ensure_ascii=True, indent=2, default=str)
    if len(rendered) > 3900:
        rendered = f"{rendered[:3897]}..."
    return discord.Embed(
        title=title, description=f"```json\n{rendered}\n```", color=discord.Color.blurple()
    )


async def _session(
    sessions: WizardSessionStore,
    interaction: discord.Interaction,
    flow_id: str,
) -> dict[str, Any]:
    state = await sessions.get(interaction.user.id, flow_id)
    if state is None:
        raise ValueError("This form expired. Run the command again.")
    return state
