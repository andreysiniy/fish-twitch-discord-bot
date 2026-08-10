"""Discord /fish players commands (module-per-domain)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import discord
from discord import app_commands

from app.api.errors import EngineError
from app.interactions.confirms import ConfirmView
from app.presentation.embeds import (
    player_inventory_embed,
    player_modifiers_embed,
    player_overflow_embed,
    player_stats_explain_embed,
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
    _mutation_response,
    _parse_effects,
    _player_modifier_preview_embed,
    _send_error,
    _session,
    _simple_mutation,
)



async def _resolve_viewer(api, interaction, viewer: str | None) -> str:
    """Return a viewer identifier for player commands.

    Accepts a Twitch username (or legacy numeric id); when omitted, falls back
    to the invoking administrator's own linked Twitch account.
    """
    if viewer and viewer.strip():
        return viewer.strip()
    status = await api.status(interaction)
    twitch = (status or {}).get("twitch") or {}
    login = twitch.get("login")
    if not login:
        raise EngineError(
            400,
            "LINK_REQUIRED",
            "Link your Twitch account first, or pass a viewer username.",
        )
    return login

def register_players_group(tree, api, sessions, fish) -> None:
        player = app_commands.Group(
            name="player", description="Manage player inventories", parent=fish
        )

        @player.command(name="inventory", description="Show every player inventory field")
        @app_commands.describe(viewer="Viewer Twitch username; omit to use your own account")
        async def player_inventory(
            interaction: discord.Interaction, viewer: str | None = None
        ) -> None:
            async def operation() -> None:
                resolved = await _resolve_viewer(api, interaction, viewer)
                result = await api.player_inventory(interaction, resolved)
                await interaction.followup.send(
                    embed=player_inventory_embed(result, viewer=resolved), ephemeral=True
                )

            await _deferred(interaction, operation)

        @player.command(name="item-grant", description="Grant a typed item atomically")
        @app_commands.describe(viewer="Viewer Twitch username; omit to use your own account")
        async def player_item_grant(
            interaction: discord.Interaction,
            item_id: str,
            quantity: app_commands.Range[int, 1, 1_000_000] = 1,
            slot_id: app_commands.Range[int, 1, 1_000_000] | None = None,
            current_durability: app_commands.Range[int, 0, 1_000_000] | None = None,
            viewer: str | None = None,
        ) -> None:
            async def mutation() -> None:
                resolved = await _resolve_viewer(api, interaction, viewer)
                await api.grant_player_item(
                    interaction,
                    resolved,
                    {
                        "item_id": item_id,
                        "quantity": quantity,
                        "slot_id": slot_id,
                        "current_durability": current_durability,
                        "meta": {},
                    },
                )

            await _simple_mutation(interaction, mutation, "Item granted.")

        @player.command(name="item-revoke", description="Revoke a versioned inventory quantity")
        @app_commands.describe(viewer="Viewer Twitch username; omit to use your own account")
        async def player_item_revoke(
            interaction: discord.Interaction,
            inventory_item_id: int,
            quantity: app_commands.Range[int, 1, 1_000_000] = 1,
            viewer: str | None = None,
        ) -> None:
            try:
                resolved = await _resolve_viewer(api, interaction, viewer)
                inventory = await api.player_inventory(interaction, resolved)
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
                    resolved,
                    inventory_item_id,
                    quantity,
                    row["version"],
                ),
                "Inventory item revoked.",
                danger=True,
            )

        @player.command(name="overflow", description="List items parked in overflow storage")
        @app_commands.describe(viewer="Viewer Twitch username; omit to use your own account")
        async def player_overflow(
            interaction: discord.Interaction, viewer: str | None = None
        ) -> None:
            async def operation() -> None:
                resolved = await _resolve_viewer(api, interaction, viewer)
                result = await api.player_overflow(interaction, resolved)
                await interaction.followup.send(
                    embed=player_overflow_embed(result, viewer=resolved), ephemeral=True
                )

            await _deferred(interaction, operation)

        @player.command(name="overflow-claim", description="Claim all parked overflow items")
        @app_commands.describe(viewer="Viewer Twitch username; omit to use your own account")
        async def player_overflow_claim(
            interaction: discord.Interaction, viewer: str | None = None
        ) -> None:
            try:
                resolved = await _resolve_viewer(api, interaction, viewer)
                parked = await api.player_overflow(interaction, resolved)
                items = parked.get("items") or []
                if not items:
                    raise EngineError(400, "OVERFLOW_EMPTY", "No items in overflow storage")
            except (EngineError, ValueError) as error:
                await _send_error(interaction, error)
                return

            def claim_operation(confirmed: discord.Interaction):
                return api.claim_player_overflow(
                    confirmed,
                    resolved,
                    [{"id": item["id"], "version": item["version"]} for item in items],
                )

            await _confirmation(
                interaction,
                f"Claim {len(items)} item(s) parked in overflow storage for `{resolved}`?",
                claim_operation,
                "Overflow items claimed.",
                danger=False,
            )

        player_modifier = app_commands.Group(
            name="player-modifier", description="Manage player stat modifiers", parent=fish
        )

        @player_modifier.command(name="list", description="List player modifier sources")
        @app_commands.describe(viewer="Viewer Twitch username; omit to use your own account")
        async def player_modifier_list(
            interaction: discord.Interaction, viewer: str | None = None
        ) -> None:
            async def operation() -> None:
                resolved = await _resolve_viewer(api, interaction, viewer)
                result = await api.player_modifiers(interaction, resolved)
                await interaction.followup.send(
                    embed=player_modifiers_embed(result), ephemeral=True
                )

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
        @app_commands.describe(
            viewer="Viewer Twitch username; omit to use your own account",
            value="Human percentage for add/override/min/max (10 = +10%); multiplier for multiply (2 = x2)",
            expires_in="Optional duration for this modifier, e.g. 10m, 2h, 1d",
        )
        async def player_modifier_set(
            interaction: discord.Interaction,
            stat_key: app_commands.Choice[str],
            operation: app_commands.Choice[str],
            scope: app_commands.Choice[str],
            value: str,
            source_key: str,
            reason: str,
            expected_version: app_commands.Range[int, 1] | None = None,
            viewer: str | None = None,
            expires_in: str | None = None,
        ) -> None:
            payload = _player_modifier_payload(
                stat_key=stat_key.value,
                operation=operation.value,
                scope=scope.value,
                value=value,
                source_key=source_key,
                reason=reason,
                expected_version=expected_version,
                expires_in=expires_in,
            )
            expires_at = payload.get("expires_at")
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
                resolved = await _resolve_viewer(api, interaction, viewer)
                current_resolved = None
                existing_sources = []
                try:
                    explained = await api.explain_player_stats(
                        interaction, resolved, scope.value
                    )
                    for stat_key_value, stat_entry in (explained.get("stats") or {}).items():
                        if stat_key_value == stat_key.value:
                            current_resolved = stat_entry
                    players = await api.player_modifiers(interaction, resolved)
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

                display_value = (
                    value.strip()
                    if operation.value == "multiply"
                    else f"{value.strip()}%"
                )
                embed = _player_modifier_preview_embed(
                    user_twitch_id=resolved,
                    scope=scope.value,
                    stat_key=stat_key.value,
                    op_label=op_label,
                    value=display_value,
                    current_resolved=resolved_text,
                    existing_source_count=len(existing_sources),
                    source_key=source_key,
                    reason=reason,
                    expires_at=expires_at,
                )
                await interaction.edit_original_response(
                    content=None,
                    embed=embed,
                    view=ConfirmView(
                        interaction.user.id,
                        lambda confirmed: _mutation_response(
                            confirmed,
                            lambda: api.set_player_modifier(
                                confirmed, resolved, payload
                            ),
                            "Player modifier updated.",
                        ),
                    ),
                )

            await _deferred(interaction, operation)

        @player_modifier.command(name="disable", description="Disable a player modifier")
        @app_commands.describe(viewer="Viewer Twitch username; omit to use your own account")
        async def player_modifier_disable(
            interaction: discord.Interaction,
            modifier_id: str,
            viewer: str | None = None,
        ) -> None:
            try:
                resolved = await _resolve_viewer(api, interaction, viewer)
                current = await api.player_modifiers(interaction, resolved)
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
                    interaction, resolved, modifier_id, row["version"], False
                ),
                "Player modifier disabled.",
            )

        @player_modifier.command(name="remove", description="Delete a player modifier")
        @app_commands.describe(viewer="Viewer Twitch username; omit to use your own account")
        async def player_modifier_remove(
            interaction: discord.Interaction,
            modifier_id: str,
            viewer: str | None = None,
        ) -> None:
            try:
                resolved = await _resolve_viewer(api, interaction, viewer)
                current = await api.player_modifiers(interaction, resolved)
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
                    confirmed, resolved, modifier_id, row["version"]
                ),
                "Player modifier removed.",
                danger=True,
            )

        player_stats = app_commands.Group(
            name="player-stats", description="Explain resolved player stats", parent=fish
        )

        @player_stats.command(name="explain", description="Explain every resolved stat source")
        @app_commands.choices(scope=MODIFIER_SCOPE_CHOICES[:-1])
        @app_commands.describe(viewer="Viewer Twitch username; omit to use your own account")
        async def player_stats_explain(
            interaction: discord.Interaction,
            scope: app_commands.Choice[str],
            viewer: str | None = None,
        ) -> None:
            async def operation() -> None:
                resolved = await _resolve_viewer(api, interaction, viewer)
                result = await api.explain_player_stats(
                    interaction, resolved, scope.value
                )
                await interaction.followup.send(
                    embed=player_stats_explain_embed(result), ephemeral=True
                )

            await _deferred(interaction, operation)

        return {
            "player_inventory": player_inventory,
            "player_item_grant": player_item_grant,
            "player_item_revoke": player_item_revoke,
            "player_overflow": player_overflow,
            "player_overflow_claim": player_overflow_claim,
            "player_modifier_list": player_modifier_list,
            "player_modifier_set": player_modifier_set,
            "player_modifier_disable": player_modifier_disable,
            "player_modifier_remove": player_modifier_remove,
            "player_stats_explain": player_stats_explain,
        }


# Stats whose value is an absolute count, not a ratio; human-percent
# conversion must not apply to them.
_INTEGER_STATS = {
    "inventory_slots_add",
    "cooldown_seconds_flat",
}

_STAT_IS_RATIO = {name: False for name in _INTEGER_STATS}


def _player_modifier_payload(
    *,
    stat_key: str,
    operation: str,
    scope: str,
    value: str,
    source_key: str,
    reason: str,
    expected_version: int | None,
    expires_in: str | None,
) -> dict[str, Any]:
    """Build the backend payload; human percentages become ratios (10 -> 0.10).

    ``multiply`` keeps a raw multiplier (2 = x2) because the backend bounds a
    multiplier in 0..100, not a ratio. Integer-valued stats (e.g. inventory
    slots) keep the raw count. ``expires_in`` is a duration string such as
    "2h" that turns into an absolute ``expires_at`` timestamp.
    """
    is_ratio_stat = _STAT_IS_RATIO.get(stat_key, True)
    if operation == "multiply":
        ratio_value = str(Decimal(value.strip()))
    elif is_ratio_stat:
        ratio_value = str((Decimal(value.strip()) / 100))
    else:
        ratio_value = str(Decimal(value.strip()))
    expires_at = None
    if expires_in:
        seconds = parse_duration(expires_in)
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    return {
        "stat_key": stat_key,
        "operation": operation,
        "scope": scope,
        "value": ratio_value,
        "source_key": source_key,
        "reason": reason,
        "expected_version": expected_version,
        "expires_at": expires_at,
    }
