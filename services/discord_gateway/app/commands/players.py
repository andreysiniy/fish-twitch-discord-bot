"""Discord /fish players commands (module-per-domain)."""


import discord
from discord import app_commands

from app.api.errors import EngineError
from app.interactions.confirms import ConfirmView

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


def register_players_group(tree, api, sessions, fish) -> None:
        player = app_commands.Group(
            name="player", description="Manage player inventories", parent=fish
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
                    raise EngineError(404, "INVENTORY_ITEM_NOT_FOUND", "Inventory item not found")
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

        player_modifier = app_commands.Group(
            name="player-modifier", description="Manage player stat modifiers", parent=fish
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
                    raise EngineError(404, "PLAYER_MODIFIER_NOT_FOUND", "Player modifier not found")
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
                    raise EngineError(404, "PLAYER_MODIFIER_NOT_FOUND", "Player modifier not found")
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

        player_stats = app_commands.Group(
            name="player-stats", description="Explain resolved player stats", parent=fish
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

        return {
            "player_inventory": player_inventory,
            "player_item_grant": player_item_grant,
            "player_item_revoke": player_item_revoke,
            "player_modifier_list": player_modifier_list,
            "player_modifier_set": player_modifier_set,
            "player_modifier_disable": player_modifier_disable,
            "player_modifier_remove": player_modifier_remove,
            "player_stats_explain": player_stats_explain,
        }
