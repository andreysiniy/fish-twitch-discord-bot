import hmac
from dataclasses import dataclass

from core.api_errors import ApiProblem
from core.config import settings
from fastapi import Header


@dataclass(frozen=True)
class DiscordServiceContext:
    discord_user_id: str
    discord_guild_id: str | None
    request_id: str
    idempotency_key: str | None
    can_manage_guild: bool
    management_channel_id: str | None
    service_name: str = "discord_gateway"

    @property
    def actor_scope(self) -> str:
        return f"discord:{self.discord_user_id}:{self.discord_guild_id or 'dm'}"


def get_discord_service_context(
    service_name: str = Header(..., alias="X-Service-Name"),
    service_api_key: str = Header(..., alias="X-Service-API-Key"),
    discord_user_id: str = Header(..., alias="X-Discord-User-ID"),
    discord_guild_id: str | None = Header(None, alias="X-Discord-Guild-ID"),
    request_id: str = Header(..., alias="X-Request-ID"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    can_manage_guild: bool = Header(False, alias="X-Discord-Manage-Guild"),
    management_channel_id: str | None = Header(None, alias="X-Discord-Channel-ID"),
) -> DiscordServiceContext:
    if service_name != "discord_gateway" or not hmac.compare_digest(
        service_api_key,
        settings.DISCORD_BOT_API_KEY,
    ):
        raise ApiProblem(401, "PERMISSION_DENIED", "Invalid service credentials", request_id=request_id)
    if not discord_user_id.isdigit() or (discord_guild_id and not discord_guild_id.isdigit()):
        raise ApiProblem(400, "VALIDATION_ERROR", "Invalid Discord context", request_id=request_id)
    return DiscordServiceContext(
        discord_user_id=discord_user_id,
        discord_guild_id=discord_guild_id,
        request_id=request_id,
        idempotency_key=idempotency_key,
        can_manage_guild=can_manage_guild,
        management_channel_id=management_channel_id,
    )
