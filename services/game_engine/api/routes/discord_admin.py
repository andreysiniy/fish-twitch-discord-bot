from api.dependencies import get_discord_admin_service
from api.discord_dependencies import DiscordServiceContext, get_discord_service_context
from core.api_errors import ApiProblem
from domain.config_schema import GameConfig
from domain.schemas.discord_admin import (
    ConfigPatchRequest,
    ConfigResetRequest,
    DiscordEventCreateRequest,
    DiscordEventPatchRequest,
    DiscordEventStartRequest,
    LocationCreateRequest,
    LocationPatchRequest,
    RewardCreateRequest,
    RewardPatchRequest,
)
from fastapi import APIRouter, Depends, Query
from services.discord_admin_service import CONFIG_SECTIONS, DiscordAdminService

router = APIRouter()


@router.get("/channels/{channel_twitch_id}/config/schema")
def config_schema(
    channel_twitch_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    service.get_config(context, channel_twitch_id)
    schema = GameConfig.model_json_schema()
    properties = schema.get("properties", {})
    return {
        "schema_version": 1,
        "sections": {
            section: {"fields": {field: properties[field] for field in sorted(fields)}}
            for section, fields in CONFIG_SECTIONS.items()
        },
    }


@router.get("/channels/{channel_twitch_id}/config")
def get_config(
    channel_twitch_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.get_config(context, channel_twitch_id)


@router.patch("/channels/{channel_twitch_id}/config")
def patch_config(
    channel_twitch_id: str,
    data: ConfigPatchRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.patch_config(context, channel_twitch_id, data)


@router.post("/channels/{channel_twitch_id}/config/reset")
def reset_config(
    channel_twitch_id: str,
    data: ConfigResetRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.reset_config(context, channel_twitch_id, data)


@router.get("/channels/{channel_twitch_id}/locations")
def list_locations(
    channel_twitch_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.list_locations(context, channel_twitch_id)


@router.post("/channels/{channel_twitch_id}/locations")
def create_location(
    channel_twitch_id: str,
    data: LocationCreateRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.create_location(context, channel_twitch_id, data)


@router.get("/channels/{channel_twitch_id}/locations/{location_id}")
def get_location(
    channel_twitch_id: str,
    location_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.get_location(context, channel_twitch_id, location_id)


@router.patch("/channels/{channel_twitch_id}/locations/{location_id}")
def patch_location(
    channel_twitch_id: str,
    location_id: str,
    data: LocationPatchRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.patch_location(context, channel_twitch_id, location_id, data)


@router.delete("/channels/{channel_twitch_id}/locations/{location_id}")
def delete_location(
    channel_twitch_id: str,
    location_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.delete_location(context, channel_twitch_id, location_id)


@router.get("/channels/{channel_twitch_id}/locations/{location_id}/rewards")
def list_rewards(
    channel_twitch_id: str,
    location_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.list_rewards(context, channel_twitch_id, location_id)


@router.post("/channels/{channel_twitch_id}/locations/{location_id}/rewards")
def create_reward(
    channel_twitch_id: str,
    location_id: str,
    data: RewardCreateRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.create_reward(context, channel_twitch_id, location_id, data)


@router.get("/channels/{channel_twitch_id}/locations/{location_id}/rewards/{reward_id}")
def get_reward(
    channel_twitch_id: str,
    location_id: str,
    reward_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    rewards = service.list_rewards(context, channel_twitch_id, location_id)
    reward = next(
        (item for item in rewards["items"] if item["reward_id"] == reward_id),
        None,
    )
    if not reward:
        raise ApiProblem(404, "REWARD_NOT_FOUND", "Reward not found")
    return reward


@router.patch("/channels/{channel_twitch_id}/locations/{location_id}/rewards/{reward_id}")
def patch_reward(
    channel_twitch_id: str,
    location_id: str,
    reward_id: str,
    data: RewardPatchRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.patch_reward(context, channel_twitch_id, location_id, reward_id, data)


@router.delete("/channels/{channel_twitch_id}/locations/{location_id}/rewards/{reward_id}")
def delete_reward(
    channel_twitch_id: str,
    location_id: str,
    reward_id: str,
    expected_version: int = Query(..., ge=1),
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.delete_reward(
        context,
        channel_twitch_id,
        location_id,
        reward_id,
        expected_version,
    )


@router.get("/channels/{channel_twitch_id}/events")
def list_events(
    channel_twitch_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.list_events(context, channel_twitch_id)


@router.post("/channels/{channel_twitch_id}/events")
def create_event(
    channel_twitch_id: str,
    data: DiscordEventCreateRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.create_event(context, channel_twitch_id, data)


@router.get("/channels/{channel_twitch_id}/events/{event_id:int}")
def get_event(
    channel_twitch_id: str,
    event_id: int,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.get_event(context, channel_twitch_id, event_id)


@router.patch("/channels/{channel_twitch_id}/events/{event_id:int}")
def patch_event(
    channel_twitch_id: str,
    event_id: int,
    data: DiscordEventPatchRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.patch_event(context, channel_twitch_id, event_id, data)


@router.post("/channels/{channel_twitch_id}/events/{event_id:int}/start")
def start_event(
    channel_twitch_id: str,
    event_id: int,
    data: DiscordEventStartRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.start_event(context, channel_twitch_id, event_id, data)


@router.post("/channels/{channel_twitch_id}/events/stop")
def stop_event(
    channel_twitch_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.stop_event(context, channel_twitch_id)


@router.delete("/channels/{channel_twitch_id}/events/{event_id:int}")
def delete_event(
    channel_twitch_id: str,
    event_id: int,
    expected_version: int = Query(..., ge=1),
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.delete_event(context, channel_twitch_id, event_id, expected_version)
# ruff: noqa: B008
