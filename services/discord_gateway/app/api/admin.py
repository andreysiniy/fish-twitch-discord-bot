from typing import Any

import discord

from app.api.client import EngineClient
from app.api.errors import EngineError
from app.api.idempotency import interaction_key


class AdminApi:
    def __init__(self, client: EngineClient):
        self.client = client

    async def status(self, interaction: discord.Interaction) -> dict[str, Any]:
        return await self.client.request(interaction, "GET", "/v1/integrations/discord/link/status")

    async def message_placeholders(self, interaction: discord.Interaction) -> dict[str, Any]:
        return await self.client.request(
            interaction,
            "GET",
            "/v1/integrations/discord/messages/placeholders",
        )

    async def link_start(self, interaction: discord.Interaction) -> dict[str, Any]:
        return await self.client.request(
            interaction,
            "POST",
            "/v1/integrations/discord/link/start",
            idempotency_key=interaction_key(interaction.id, "link.start"),
        )

    async def unlink(self, interaction: discord.Interaction) -> dict[str, Any]:
        return await self.client.request(
            interaction,
            "DELETE",
            "/v1/integrations/discord/link",
            idempotency_key=interaction_key(interaction.id, "link.unlink"),
        )

    async def setup(
        self, interaction: discord.Interaction, replace: bool = False
    ) -> dict[str, Any]:
        if not interaction.guild_id:
            raise EngineError(403, "GUILD_BINDING_REQUIRED", "Guild context required")
        return await self.client.request(
            interaction,
            "POST",
            f"/v1/integrations/discord/guilds/{interaction.guild_id}/bind",
            json={"replace": replace},
            idempotency_key=interaction_key(interaction.id, "guild.bind"),
        )

    async def setup_remove(self, interaction: discord.Interaction) -> dict[str, Any]:
        if not interaction.guild_id:
            raise EngineError(403, "GUILD_BINDING_REQUIRED", "Guild context required")
        return await self.client.request(
            interaction,
            "DELETE",
            f"/v1/integrations/discord/guilds/{interaction.guild_id}/bind",
            idempotency_key=interaction_key(interaction.id, "guild.unbind"),
        )

    async def channel_id(self, interaction: discord.Interaction) -> str:
        status = await self.status(interaction)
        binding = status.get("binding")
        if not binding:
            raise EngineError(403, "GUILD_BINDING_REQUIRED", "Guild binding required")
        return str(binding["channel_twitch_id"])

    async def config(self, interaction: discord.Interaction) -> dict[str, Any]:
        channel = await self.channel_id(interaction)
        return await self.client.request(interaction, "GET", f"/v1/admin/channels/{channel}/config")

    async def config_schema(self, interaction: discord.Interaction) -> dict[str, Any]:
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "GET",
            f"/v1/admin/channels/{channel}/config/schema",
        )

    async def messages(self, interaction: discord.Interaction) -> dict[str, Any]:
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "GET",
            f"/v1/admin/channels/{channel}/messages",
        )

    async def patch_message(
        self,
        interaction: discord.Interaction,
        message_key: str,
        version: int,
        template: str | None,
    ) -> dict[str, Any]:
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "PATCH",
            f"/v1/admin/channels/{channel}/messages/{message_key}",
            json={"expected_version": version, "template": template},
            idempotency_key=interaction_key(interaction.id, "message.patch"),
        )

    async def patch_config(self, interaction, version: int, changes: dict[str, Any]):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "PATCH",
            f"/v1/admin/channels/{channel}/config",
            json={"expected_version": version, "changes": changes},
            idempotency_key=interaction_key(interaction.id, "config.patch"),
        )

    async def reset_config(self, interaction, version: int, section: str):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "POST",
            f"/v1/admin/channels/{channel}/config/reset",
            json={"expected_version": version, "section": section},
            idempotency_key=interaction_key(interaction.id, "config.reset"),
        )

    async def locations(self, interaction):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction, "GET", f"/v1/admin/channels/{channel}/locations"
        )

    async def location(self, interaction, location_id):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "GET",
            f"/v1/admin/channels/{channel}/locations/{location_id}",
        )

    async def create_location(self, interaction, payload):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "POST",
            f"/v1/admin/channels/{channel}/locations",
            json=payload,
            idempotency_key=interaction_key(interaction.id, "location.create"),
        )

    async def patch_location(self, interaction, location_id, payload):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "PATCH",
            f"/v1/admin/channels/{channel}/locations/{location_id}",
            json=payload,
            idempotency_key=interaction_key(interaction.id, "location.patch"),
        )

    async def delete_location(self, interaction, location_id):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "DELETE",
            f"/v1/admin/channels/{channel}/locations/{location_id}",
            idempotency_key=interaction_key(interaction.id, "location.delete"),
        )

    async def rewards(self, interaction, location_id):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "GET",
            f"/v1/admin/channels/{channel}/locations/{location_id}/rewards",
        )

    async def create_reward(self, interaction, location_id, version, reward):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "POST",
            f"/v1/admin/channels/{channel}/locations/{location_id}/rewards",
            json={"expected_version": version, "reward": reward},
            idempotency_key=interaction_key(interaction.id, "reward.create"),
        )

    async def patch_reward(self, interaction, location_id, reward_id, version, reward):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "PATCH",
            f"/v1/admin/channels/{channel}/locations/{location_id}/rewards/{reward_id}",
            json={"expected_version": version, "reward": reward},
            idempotency_key=interaction_key(interaction.id, "reward.patch"),
        )

    async def delete_reward(self, interaction, location_id, reward_id, version):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "DELETE",
            f"/v1/admin/channels/{channel}/locations/{location_id}/rewards/{reward_id}"
            f"?expected_version={version}",
            idempotency_key=interaction_key(interaction.id, "reward.delete"),
        )

    async def import_legacy_rewards(
        self,
        interaction,
        location_id: str,
        version: int,
        payload: dict[str, Any],
        replace_existing: bool,
        *,
        dry_run: bool,
    ) -> dict[str, Any]:
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "POST",
            f"/v1/admin/channels/{channel}/locations/{location_id}/rewards/import-legacy",
            json={
                "expected_version": version,
                "payload": payload,
                "replace_existing": replace_existing,
                "dry_run": dry_run,
            },
            idempotency_key=(
                None
                if dry_run
                else interaction_key(interaction.id, "reward.import_legacy")
            ),
        )

    async def events(self, interaction):
        channel = await self.channel_id(interaction)
        return await self.client.request(interaction, "GET", f"/v1/admin/channels/{channel}/events")

    async def event(self, interaction, event_id):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "GET",
            f"/v1/admin/channels/{channel}/events/{event_id}",
        )

    async def create_event(self, interaction, payload):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "POST",
            f"/v1/admin/channels/{channel}/events",
            json=payload,
            idempotency_key=interaction_key(interaction.id, "event.create"),
        )

    async def patch_event(self, interaction, event_id, payload):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "PATCH",
            f"/v1/admin/channels/{channel}/events/{event_id}",
            json=payload,
            idempotency_key=interaction_key(interaction.id, "event.patch"),
        )

    async def start_event(self, interaction, event_id, version, duration_seconds):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "POST",
            f"/v1/admin/channels/{channel}/events/{event_id}/start",
            json={"expected_version": version, "duration_seconds": duration_seconds},
            idempotency_key=interaction_key(interaction.id, "event.start"),
        )

    async def stop_event(self, interaction):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "POST",
            f"/v1/admin/channels/{channel}/events/stop",
            idempotency_key=interaction_key(interaction.id, "event.stop"),
        )

    async def delete_event(self, interaction, event_id, version):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "DELETE",
            f"/v1/admin/channels/{channel}/events/{event_id}?expected_version={version}",
            idempotency_key=interaction_key(interaction.id, "event.delete"),
        )

    async def items(self, interaction, include_archived: bool = False):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "GET",
            f"/v1/admin/channels/{channel}/items?include_archived={str(include_archived).lower()}",
        )

    async def item(self, interaction, item_id: str):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction, "GET", f"/v1/admin/channels/{channel}/items/{item_id}"
        )

    async def upsert_item(self, interaction, payload: dict[str, Any]):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "PUT",
            f"/v1/admin/channels/{channel}/items",
            json=payload,
            idempotency_key=interaction_key(interaction.id, "item.upsert"),
        )

    async def archive_item(self, interaction, item_id: str, version: int):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "POST",
            f"/v1/admin/channels/{channel}/items/{item_id}/archive"
            f"?expected_version={version}",
            idempotency_key=interaction_key(interaction.id, "item.archive"),
        )

    async def item_drops(self, interaction, location_id: str):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "GET",
            f"/v1/admin/channels/{channel}/locations/{location_id}/item-drops",
        )

    async def upsert_item_drop(self, interaction, location_id: str, payload: dict[str, Any]):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "PUT",
            f"/v1/admin/channels/{channel}/locations/{location_id}/item-drops",
            json=payload,
            idempotency_key=interaction_key(interaction.id, "item_drop.upsert"),
        )

    async def remove_item_drop(
        self, interaction, location_id: str, item_id: str, version: int
    ):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "DELETE",
            f"/v1/admin/channels/{channel}/locations/{location_id}/item-drops/{item_id}"
            f"?expected_version={version}",
            idempotency_key=interaction_key(interaction.id, "item_drop.remove"),
        )

    async def player_inventory(self, interaction, user_twitch_id: str):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "GET",
            f"/v1/admin/channels/{channel}/players/{user_twitch_id}/inventory",
        )

    async def grant_player_item(self, interaction, user_twitch_id: str, payload: dict[str, Any]):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "POST",
            f"/v1/admin/channels/{channel}/players/{user_twitch_id}/items",
            json=payload,
            idempotency_key=interaction_key(interaction.id, "player.item_grant"),
        )

    async def revoke_player_item(
        self,
        interaction,
        user_twitch_id: str,
        inventory_item_id: int,
        quantity: int,
        version: int,
    ):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "POST",
            f"/v1/admin/channels/{channel}/players/{user_twitch_id}/items/"
            f"{inventory_item_id}/revoke",
            json={"quantity": quantity, "expected_version": version},
            idempotency_key=interaction_key(interaction.id, "player.item_revoke"),
        )

    async def player_modifiers(self, interaction, user_twitch_id: str):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "GET",
            f"/v1/admin/channels/{channel}/players/{user_twitch_id}/modifiers",
        )

    async def set_player_modifier(
        self, interaction, user_twitch_id: str, payload: dict[str, Any]
    ):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "PUT",
            f"/v1/admin/channels/{channel}/players/{user_twitch_id}/modifiers",
            json=payload,
            idempotency_key=interaction_key(interaction.id, "player_modifier.set"),
        )

    async def set_player_modifier_state(
        self,
        interaction,
        user_twitch_id: str,
        modifier_id: str,
        version: int,
        is_enabled: bool,
    ):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "PATCH",
            f"/v1/admin/channels/{channel}/players/{user_twitch_id}/modifiers/"
            f"{modifier_id}/state",
            json={"expected_version": version, "is_enabled": is_enabled},
            idempotency_key=interaction_key(interaction.id, "player_modifier.state"),
        )

    async def remove_player_modifier(
        self, interaction, user_twitch_id: str, modifier_id: str, version: int
    ):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "DELETE",
            f"/v1/admin/channels/{channel}/players/{user_twitch_id}/modifiers/"
            f"{modifier_id}?expected_version={version}",
            idempotency_key=interaction_key(interaction.id, "player_modifier.remove"),
        )

    async def explain_player_stats(
        self, interaction, user_twitch_id: str, scope: str = "fishing"
    ):
        channel = await self.channel_id(interaction)
        return await self.client.request(
            interaction,
            "GET",
            f"/v1/admin/channels/{channel}/players/{user_twitch_id}/stats/explain"
            f"?scope={scope}",
        )
