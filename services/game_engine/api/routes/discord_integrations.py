from api.dependencies import get_discord_admin_service
from api.discord_dependencies import DiscordServiceContext, get_discord_service_context
from domain.schemas.discord_admin import GuildBindRequest
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from services.discord_admin_service import DiscordAdminService

router = APIRouter()


@router.post("/integrations/discord/link/start")
def start_link(
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.start_link(context)


@router.get("/integrations/discord/link/status")
def link_status(
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.status(context)


@router.delete("/integrations/discord/link")
def unlink(
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.unlink(context)


@router.get("/integrations/discord/guilds/{guild_id}")
def guild_status(
    guild_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    if context.discord_guild_id != guild_id:
        from core.api_errors import ApiProblem

        raise ApiProblem(403, "PERMISSION_DENIED", "Guild context mismatch")
    return service.status(context)


@router.post("/integrations/discord/guilds/{guild_id}/bind")
def bind_guild(
    guild_id: str,
    data: GuildBindRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    if context.discord_guild_id != guild_id:
        from core.api_errors import ApiProblem

        raise ApiProblem(403, "PERMISSION_DENIED", "Guild context mismatch")
    return service.bind_guild(context, data)


@router.delete("/integrations/discord/guilds/{guild_id}/bind")
def unbind_guild(
    guild_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    if context.discord_guild_id != guild_id:
        from core.api_errors import ApiProblem

        raise ApiProblem(403, "PERMISSION_DENIED", "Guild context mismatch")
    return service.remove_guild_binding(context)


@router.get("/auth/twitch/discord/callback", include_in_schema=False)
async def discord_twitch_callback(
    state: str = Query(...),
    code: str = Query(...),
    service: DiscordAdminService = Depends(get_discord_admin_service),
) -> HTMLResponse:
    result = await service.complete_link(state, code)
    login = escape(result["twitch_login"])
    return HTMLResponse(
        f"<html><body><h1>Twitch linked</h1><p>{login}</p>"
        "<p>You can return to Discord.</p></body></html>"
    )
# ruff: noqa: B008

from html import escape
