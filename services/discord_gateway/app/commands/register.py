import json
from typing import Any

import discord
from discord import app_commands

from app.api.admin import AdminApi
from app.api.errors import EngineError, localize_error
from app.commands.casts import register_casts_group
from app.interactions.confirms import ConfirmView
from app.interactions.effects_editor import EffectsEditorView
from app.interactions.launchers import ModalLauncherView
from app.interactions.modals import (
    ConfigModal,
    EventModal,
    LocationModal,
    MessageTemplateModal,
    create_reward_modal,
)
from app.interactions.sessions import WizardSessionStore
from app.presentation.embeds import (
    config_embed,
    event_list_entry,
    item_drop_list_entry,
    item_list_entry,
    legacy_import_embed,
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
    for value in ("fish", "timeout", "robbery", "russian_roulette", "dupe", "nothing")
]
ITEM_TYPE_CHOICES = [
    app_commands.Choice(name=value.title(), value=value)
    for value in (
        "equipment",
        "consumable",
        "lootbox",
        "material",
        "quest",
        "currency",
        "collectible",
    )
]
RARITY_CHOICES = [
    app_commands.Choice(name=value.title(), value=value)
    for value in ("common", "rare", "epic", "legendary")
]
EQUIPMENT_SLOT_CHOICES = [
    app_commands.Choice(name=value.replace("_", " ").title(), value=value)
    for value in ("rod", "bait", "defense", "storage", "charm_1", "charm_2")
]
BREAK_POLICY_CHOICES = [
    app_commands.Choice(name=value.replace("_", " ").title(), value=value)
    for value in ("indestructible", "retain_broken", "unequip_broken", "destroy_at_zero")
]
MODIFIER_OPERATION_CHOICES = [
    app_commands.Choice(name=value.title(), value=value)
    for value in ("add", "multiply", "override", "min", "max")
]
MODIFIER_SCOPE_CHOICES = [
    app_commands.Choice(name=value.title(), value=value)
    for value in ("fishing", "robbery", "economy", "inventory", "all")
]
STAT_KEY_CHOICES = [
    app_commands.Choice(name=value.replace("_", " ").title(), value=value)
    for value in (
        "loot_luck_pct",
        "positive_mass_bonus_pct",
        "negative_mass_reduction_pct",
        "xp_gain_bonus_pct",
        "points_flat_bonus",
        "item_drop_chance_add",
        "item_rarity_luck_pct",
        "cooldown_reduction_pct",
        "empty_catch_reroll_chance_pct",
        "robbery_protection_pct",
        "robbery_evasion_pct",
        "protected_mass_flat",
        "robbery_counter_chance_pct",
        "robbery_attack_chance_add",
        "robbery_amount_bonus_pct",
        "inventory_slots_add",
        "sell_rate_bonus_pct",
        "buy_discount_pct",
    )
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
    placeholders = app_commands.Group(
        name="placeholders",
        description="View and edit custom message templates",
        parent=fish,
    )
    item = app_commands.Group(name="item", description="Manage typed item definitions", parent=fish)
    item_drop = app_commands.Group(
        name="item-drop", description="Manage location item drops", parent=fish
    )
    player = app_commands.Group(
        name="player", description="Manage player inventories", parent=fish
    )
    player_modifier = app_commands.Group(
        name="player-modifier", description="Manage player stat modifiers", parent=fish
    )
    player_stats = app_commands.Group(
        name="player-stats", description="Explain resolved player stats", parent=fish
    )
    register_casts_group(tree, api, fish)

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
            "`placeholders` — message placeholder reference\n"
            "`cast` — fishing cast history and statistics"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
            await _send_json_embed(interaction, "Location", item)

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
                page_size=1,
            )
            await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)

        await _deferred(interaction, operation)

    @item.command(name="show", description="Show every field of one item definition")
    async def item_show(interaction: discord.Interaction, item_id: str) -> None:
        async def operation() -> None:
            result = await api.item(interaction, item_id)
            await _send_json_embed(interaction, "Item definition", result)

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
        effects_json="Strict JSON array of typed effects; omit for no effects",
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
        effects_json: str | None = None,
        description: str | None = None,
    ) -> None:
        try:
            payload = _item_payload(
                item_id=item_id,
                title=title,
                item_type=item_type.value,
                rarity=rarity.value,
                equipment_slot=equipment_slot.value if equipment_slot else None,
                stack_size=stack_size,
                max_durability=max_durability,
                break_policy=(
                    break_policy.value if break_policy else "indestructible"
                ),
                effects=_parse_effects(effects_json),
                description=description,
            )
        except ValueError as error:
            await _send_error(interaction, error)
            return
        await _json_confirmation(
            interaction,
            "Item creation preview",
            payload,
            lambda confirmed: api.upsert_item(confirmed, payload),
            "Item definition created.",
        )

    @item.command(name="edit", description="Replace a versioned typed item definition")
    @app_commands.choices(
        item_type=ITEM_TYPE_CHOICES,
        rarity=RARITY_CHOICES,
        equipment_slot=EQUIPMENT_SLOT_CHOICES,
        break_policy=BREAK_POLICY_CHOICES,
    )
    @app_commands.describe(
        item_id="Existing stable item ID",
        effects_json="Strict JSON effect array; omit to preserve current effects",
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
        effects_json: str | None = None,
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
                effects=(
                    _parse_effects(effects_json)
                    if effects_json is not None
                    else current["effects"]
                ),
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

    @item_drop.command(name="list", description="List item drops for a location")
    async def item_drop_list(interaction: discord.Interaction, location_id: str) -> None:
        async def operation() -> None:
            result = await api.item_drops(interaction, location_id)
            view = PagedEmbedView(
                interaction.user.id,
                f"Item drops — {location_id}",
                result["items"],
                item_drop_list_entry,
                page_size=1,
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
                await api.upsert_item_drop(
                    confirmed,
                    location_id,
                    {
                        "item_id": item_id,
                        "weight": weight,
                        "xp_gain": xp_gain,
                        "quantity": quantity,
                        "message": message,
                    },
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
                raise ValueError(f"Item drop not found: {item_id}")
            await api.upsert_item_drop(
                interaction,
                location_id,
                {
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
                },
            )
            await interaction.followup.send("Item drop updated.", ephemeral=True)

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
                raise ValueError(f"Item drop not found: {item_id}")
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

    @player.command(name="inventory", description="Show every player inventory field")
    async def player_inventory(
        interaction: discord.Interaction, user_twitch_id: str
    ) -> None:
        async def operation() -> None:
            result = await api.player_inventory(interaction, user_twitch_id)
            await _send_json_embed(interaction, "Player inventory", result)

        await _deferred(interaction, operation)

    @player.command(name="item-grant", description="Grant a typed item atomically")
    async def player_item_grant(
        interaction: discord.Interaction,
        user_twitch_id: str,
        item_id: str,
        quantity: app_commands.Range[int, 1, 1_000_000] = 1,
        slot_id: app_commands.Range[int, 1, 1_000_000] | None = None,
        current_durability: app_commands.Range[int, 0, 1_000_000] | None = None,
    ) -> None:
        await _simple_mutation(
            interaction,
            lambda: api.grant_player_item(
                interaction,
                user_twitch_id,
                {
                    "item_id": item_id,
                    "quantity": quantity,
                    "slot_id": slot_id,
                    "current_durability": current_durability,
                    "meta": {},
                },
            ),
            "Item granted.",
        )

    @player.command(name="item-revoke", description="Revoke a versioned inventory quantity")
    async def player_item_revoke(
        interaction: discord.Interaction,
        user_twitch_id: str,
        inventory_item_id: int,
        quantity: app_commands.Range[int, 1, 1_000_000] = 1,
    ) -> None:
        try:
            inventory = await api.player_inventory(interaction, user_twitch_id)
            row = next(
                (entry for entry in inventory["items"] if entry["id"] == inventory_item_id),
                None,
            )
            if not row:
                raise ValueError(f"Inventory item not found: {inventory_item_id}")
        except (EngineError, ValueError) as error:
            await _send_error(interaction, error)
            return
        await _confirmation(
            interaction,
            f"Revoke {quantity} from inventory item `{inventory_item_id}`?",
            lambda confirmed: api.revoke_player_item(
                confirmed,
                user_twitch_id,
                inventory_item_id,
                quantity,
                row["version"],
            ),
            "Inventory item revoked.",
            danger=True,
        )

    @player_modifier.command(name="list", description="List player modifier sources")
    async def player_modifier_list(
        interaction: discord.Interaction, user_twitch_id: str
    ) -> None:
        async def operation() -> None:
            result = await api.player_modifiers(interaction, user_twitch_id)
            await _send_json_embed(interaction, "Player modifiers", result)

        await _deferred(interaction, operation)

    @player_modifier.command(name="set", description="Create or update a player modifier")
    @app_commands.choices(
        stat_key=STAT_KEY_CHOICES,
        operation=MODIFIER_OPERATION_CHOICES,
        scope=MODIFIER_SCOPE_CHOICES,
    )
    @app_commands.describe(
        value="Decimal value; add/override uses the stat cap, multiply uses 0 to 100",
        source_key="Stable source ID, for example promotion.weekly",
        reason="Human-readable reason shown by stats explain",
        expected_version="Required only when updating an existing source",
    )
    async def player_modifier_set(
        interaction: discord.Interaction,
        user_twitch_id: str,
        stat_key: app_commands.Choice[str],
        operation: app_commands.Choice[str],
        scope: app_commands.Choice[str],
        value: str,
        source_key: str,
        reason: str,
        expected_version: app_commands.Range[int, 1] | None = None,
    ) -> None:
        payload = {
            "stat_key": stat_key.value,
            "operation": operation.value,
            "scope": scope.value,
            "value": value,
            "source_key": source_key,
            "reason": reason,
            "expected_version": expected_version,
        }
        op_label = {
            "add": "Add",
            "multiply": "Multiply",
            "override": "Override",
            "min": "Set minimum",
            "max": "Set maximum",
        }.get(operation.value, operation.value)

        async def operation() -> None:
            # Show the current resolved value for this stat before applying,
            # so an additive/override change is never applied blind.
            current_resolved = None
            existing_sources = []
            try:
                explained = await api.explain_player_stats(
                    interaction, user_twitch_id, scope.value
                )
                for stat_key_value, stat_entry in (explained.get("stats") or {}).items():
                    if stat_key_value == stat_key.value:
                        current_resolved = stat_entry
                players = await api.player_modifiers(interaction, user_twitch_id)
                existing_sources = [
                    entry
                    for entry in players.get("items", [])
                    if entry.get("stat_key") == stat_key.value
                ]
            except EngineError:
                pass  # preview is best-effort; the mutation still proceeds

            resolved_text = "unknown"
            if current_resolved is not None:
                resolved_text = str(current_resolved.get("value"))
            if isinstance(current_resolved, dict) and "value" in current_resolved:
                resolved_text = str(current_resolved["value"])

            embed = _player_modifier_preview_embed(
                user_twitch_id=user_twitch_id,
                scope=scope.value,
                stat_key=stat_key.value,
                op_label=op_label,
                value=value,
                current_resolved=resolved_text,
                existing_source_count=len(existing_sources),
                source_key=source_key,
                reason=reason,
            )
            await interaction.edit_original_response(
                content=None,
                embed=embed,
                view=ConfirmView(
                    interaction.user.id,
                    lambda confirmed: api.set_player_modifier(
                        confirmed, user_twitch_id, payload
                    ),
                ),
            )

        await _deferred(interaction, operation)

    @player_modifier.command(name="disable", description="Disable a player modifier")
    async def player_modifier_disable(
        interaction: discord.Interaction, user_twitch_id: str, modifier_id: str
    ) -> None:
        try:
            current = await api.player_modifiers(interaction, user_twitch_id)
            row = next(
                (entry for entry in current["items"] if entry["id"] == modifier_id),
                None,
            )
            if not row:
                raise ValueError(f"Player modifier not found: {modifier_id}")
        except (EngineError, ValueError) as error:
            await _send_error(interaction, error)
            return
        await _simple_mutation(
            interaction,
            lambda: api.set_player_modifier_state(
                interaction, user_twitch_id, modifier_id, row["version"], False
            ),
            "Player modifier disabled.",
        )

    @player_modifier.command(name="remove", description="Delete a player modifier")
    async def player_modifier_remove(
        interaction: discord.Interaction, user_twitch_id: str, modifier_id: str
    ) -> None:
        try:
            current = await api.player_modifiers(interaction, user_twitch_id)
            row = next(
                (entry for entry in current["items"] if entry["id"] == modifier_id),
                None,
            )
            if not row:
                raise ValueError(f"Player modifier not found: {modifier_id}")
        except (EngineError, ValueError) as error:
            await _send_error(interaction, error)
            return
        await _confirmation(
            interaction,
            f"Delete player modifier `{modifier_id}`?",
            lambda confirmed: api.remove_player_modifier(
                confirmed, user_twitch_id, modifier_id, row["version"]
            ),
            "Player modifier removed.",
            danger=True,
        )

    @player_stats.command(name="explain", description="Explain every resolved stat source")
    @app_commands.choices(scope=MODIFIER_SCOPE_CHOICES[:-1])
    async def player_stats_explain(
        interaction: discord.Interaction,
        user_twitch_id: str,
        scope: app_commands.Choice[str],
    ) -> None:
        async def operation() -> None:
            result = await api.explain_player_stats(
                interaction, user_twitch_id, scope.value
            )
            await _send_json_embed(interaction, "Resolved player stats", result)

        await _deferred(interaction, operation)

    async def message_key_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        try:
            result = await api.message_placeholders(interaction)
        except EngineError:
            return []
        needle = current.casefold()
        return [
            app_commands.Choice(name=item["message_key"][:100], value=item["message_key"])
            for item in result["items"]
            if needle in item["message_key"].casefold()
        ][:25]

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

    async def item_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        try:
            result = await api.items(interaction, include_archived=True)
        except EngineError:
            return []
        needle = current.casefold()
        return [
            app_commands.Choice(
                name=f"{entry['title']} ({entry['item_id']})"[:100],
                value=entry["item_id"],
            )
            for entry in result["items"]
            if needle in entry["item_id"].casefold()
            or needle in entry["title"].casefold()
        ][:25]

    for command in (
        location_show,
        location_edit,
        location_delete,
        reward_list,
        reward_add,
        reward_import_legacy,
    ):
        command.autocomplete("location_id")(location_autocomplete)
    for command in (reward_show, reward_edit, reward_delete):
        command.autocomplete("location_id")(location_autocomplete)
        command.autocomplete("reward_id")(reward_autocomplete)
    for command in (event_show, event_edit, event_start, event_delete):
        command.autocomplete("event_id")(event_autocomplete)
    for command in (placeholders_show, placeholders_edit):
        command.autocomplete("message_key")(message_key_autocomplete)
    for command in (item_show, item_edit, item_archive):
        command.autocomplete("item_id")(item_autocomplete)
    for command in (item_drop_list, item_drop_add, item_drop_edit, item_drop_remove):
        command.autocomplete("location_id")(location_autocomplete)
    for command in (item_drop_add, item_drop_edit, item_drop_remove, player_item_grant):
        command.autocomplete("item_id")(item_autocomplete)

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


async def _json_confirmation(
    interaction,
    title: str,
    payload: dict[str, Any],
    operation,
    success: str,
) -> None:
    async def confirm(confirmed: discord.Interaction) -> None:
        await _mutation_response(confirmed, lambda: operation(confirmed), success)

    embed = _json_embed(title, payload)
    view = ConfirmView(interaction.user.id, confirm)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embed=embed, view=view)
    else:
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


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
    rendered = json.dumps(item, ensure_ascii=False, indent=2, default=str)
    if len(rendered) > 3900:
        rendered = f"{rendered[:3897]}…\n(полный JSON во вложении)"
    return discord.Embed(
        title=title, description=f"```json\n{rendered}\n```", color=discord.Color.blurple()
    )


def _player_modifier_preview_embed(
    *,
    user_twitch_id: str,
    scope: str,
    stat_key: str,
    op_label: str,
    value: str,
    current_resolved: str,
    existing_source_count: int,
    source_key: str,
    reason: str,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Player modifier preview — {user_twitch_id}",
        description=(
            f"Scope: `{scope}` · Stat: `{stat_key}`\n"
            f"Operation: **{op_label}** with value `{value}`"
        ),
        color=discord.Color.orange(),
    )
    embed.add_field(
        name="Current resolved value",
        value=current_resolved,
        inline=True,
    )
    embed.add_field(
        name="Existing sources",
        value=str(existing_source_count),
        inline=True,
    )
    embed.add_field(
        name="Source",
        value=f"{source_key}\n{reason}",
        inline=False,
    )
    if op_label.lower() == "override" or existing_source_count:
        embed.add_field(
            name="⚠️ Warning",
            value=(
                "This targets a stat that already has modifiers. "
                "Override replaces the resolved value; add/multiply stacks "
                "on top of the current total."
            ),
            inline=False,
        )
    return embed


async def _send_json_embed(
    interaction: discord.Interaction,
    title: str,
    item: dict[str, Any],
) -> None:
    """Не молча обрезает JSON: при превышении лимита прикладывает файл."""
    rendered = json.dumps(item, ensure_ascii=False, indent=2, default=str)
    embed = _json_embed(title, item)
    kwargs: dict[str, Any] = {"ephemeral": True}
    if len(rendered) > 3900:
        embed.description = f"```json\n{rendered[:900]}\n```\n(полный JSON во вложении)"
        kwargs["file"] = discord.File(
            discord.utils.MaybeUnicodeIO(rendered), filename=f"{title.lower()}.json"
        )
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, **kwargs)
    else:
        await interaction.response.send_message(embed=embed, **kwargs)


async def _session(
    sessions: WizardSessionStore,
    interaction: discord.Interaction,
    flow_id: str,
) -> dict[str, Any]:
    state = await sessions.get(interaction.user.id, flow_id)
    if state is None:
        raise ValueError("This form expired. Run the command again.")
    return state


def _parse_effects(raw: str | None) -> list[dict[str, Any]]:
    if raw is None or not raw.strip():
        return []
    try:
        effects = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"Effects must be valid JSON: {error.msg}") from error
    if not isinstance(effects, list) or not all(isinstance(item, dict) for item in effects):
        raise ValueError("Effects must be a JSON array of objects")
    return effects


def _item_payload(
    *,
    item_id: str,
    title: str,
    item_type: str,
    rarity: str,
    equipment_slot: str | None,
    stack_size: int,
    max_durability: int | None,
    break_policy: str,
    effects: list[dict[str, Any]],
    description: str | None,
) -> dict[str, Any]:
    if item_type == "equipment" and not equipment_slot:
        raise ValueError("Equipment slot is required for equipment")
    if item_type != "equipment" and equipment_slot:
        raise ValueError("Equipment slot is only available for equipment")
    if item_type == "equipment" and stack_size != 1:
        raise ValueError("Equipment must use stack size 1")
    if break_policy != "indestructible" and max_durability is None:
        raise ValueError("Maximum durability is required for breakable items")
    return {
        "item_id": item_id.strip().lower(),
        "title": title.strip(),
        "description": description.strip() if description else None,
        "item_type": item_type,
        "equipment_slot": equipment_slot,
        "rarity": rarity,
        "stack_size": stack_size,
        "max_durability": max_durability,
        "break_policy": break_policy,
        "schema_version": 1,
        "effects": effects,
        "image_url": None,
        "value": None,
    }
