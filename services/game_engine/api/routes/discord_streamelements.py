"""Service-context API for Discord StreamElements administration."""

# FastAPI resolves these dependency factories at request time.
# ruff: noqa: B008

from api.dependencies import get_streamelements_integration_service
from api.discord_dependencies import DiscordServiceContext, get_discord_service_context
from core.api_errors import ApiProblem
from domain.schemas.discord_admin import EconomySettingsPatchRequest, StreamElementsConnectRequest
from fastapi import APIRouter, Depends, Query
from services.idempotency_service import IdempotencyService
from services.streamelements_integration_service import StreamElementsIntegrationService

router = APIRouter()


def _require_idempotency(context: DiscordServiceContext) -> None:
    if not context.idempotency_key:
        raise ApiProblem(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "Idempotency-Key is required",
            request_id=context.request_id,
        )


@router.get("/channels/{channel_twitch_id}/streamelements")
def status(
    channel_twitch_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: StreamElementsIntegrationService = Depends(get_streamelements_integration_service),
):
    return service.status(context, channel_twitch_id)


@router.put("/channels/{channel_twitch_id}/streamelements")
async def connect(
    channel_twitch_id: str,
    data: StreamElementsConnectRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: StreamElementsIntegrationService = Depends(get_streamelements_integration_service),
):
    _require_idempotency(context)
    return await IdempotencyService(service.db).execute_async(
        context.actor_scope,
        context.idempotency_key,
        "streamelements.connect",
        {"channel_twitch_id": channel_twitch_id, "jwt_token": data.jwt_token},
        context.request_id,
        lambda: service.connect(context, channel_twitch_id, data.jwt_token),
    )


@router.delete("/channels/{channel_twitch_id}/streamelements")
def disconnect(
    channel_twitch_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: StreamElementsIntegrationService = Depends(get_streamelements_integration_service),
):
    _require_idempotency(context)
    return IdempotencyService(service.db).execute(
        context.actor_scope,
        context.idempotency_key,
        "streamelements.disconnect",
        {"channel_twitch_id": channel_twitch_id},
        context.request_id,
        lambda: service.disconnect(context, channel_twitch_id),
    )


@router.post("/channels/{channel_twitch_id}/streamelements/test")
async def test(
    channel_twitch_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: StreamElementsIntegrationService = Depends(get_streamelements_integration_service),
):
    _require_idempotency(context)
    return await IdempotencyService(service.db).execute_async(
        context.actor_scope,
        context.idempotency_key,
        "streamelements.test",
        {"channel_twitch_id": channel_twitch_id},
        context.request_id,
        lambda: service.test(context, channel_twitch_id),
    )


@router.get("/channels/{channel_twitch_id}/economy-settings")
def get_settings(
    channel_twitch_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: StreamElementsIntegrationService = Depends(get_streamelements_integration_service),
):
    return service.settings(context, channel_twitch_id)


@router.patch("/channels/{channel_twitch_id}/economy-settings")
def patch_settings(
    channel_twitch_id: str,
    data: EconomySettingsPatchRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: StreamElementsIntegrationService = Depends(get_streamelements_integration_service),
):
    _require_idempotency(context)
    return IdempotencyService(service.db).execute(
        context.actor_scope,
        context.idempotency_key,
        "streamelements.settings.update",
        {"channel_twitch_id": channel_twitch_id, **data.model_dump(mode="json")},
        context.request_id,
        lambda: service.patch_settings(context, channel_twitch_id, data),
    )


@router.get("/channels/{channel_twitch_id}/economy-operations")
def operations(
    channel_twitch_id: str,
    limit: int = Query(25, ge=1, le=100),
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: StreamElementsIntegrationService = Depends(get_streamelements_integration_service),
):
    return service.operations(context, channel_twitch_id, limit)
