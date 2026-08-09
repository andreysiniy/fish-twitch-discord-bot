from api.dependencies import get_discord_admin_service
from api.discord_dependencies import DiscordServiceContext, get_discord_service_context
from core.api_errors import ApiProblem
from domain.config_schema import GameConfig
from domain.item_schema import ModifierScope
from domain.schemas.discord_admin import (
    ConfigPatchRequest,
    ConfigResetRequest,
    DiscordEventCreateRequest,
    DiscordEventPatchRequest,
    DiscordEventStartRequest,
    DiscordItemUpsertRequest,
    ItemDropUpsertRequest,
    LegacyRewardImportRequest,
    LocationCreateRequest,
    LocationPatchRequest,
    MessageTemplatePatchRequest,
    PlayerItemGrantRequest,
    PlayerItemRevokeRequest,
    PlayerModifierSetRequest,
    RewardCreateRequest,
    RewardPatchRequest,
    VersionedStateRequest,
)
from fastapi import APIRouter, Depends, Query
from services.discord_admin_service import CONFIG_SECTIONS, DiscordAdminService

router = APIRouter()


@router.get("/channels/{channel_twitch_id}/items")
def list_items(
    channel_twitch_id: str,
    include_archived: bool = False,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.list_items(context, channel_twitch_id, include_archived)


@router.get("/channels/{channel_twitch_id}/loot-tables")
def list_loot_tables(
    channel_twitch_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.list_loot_tables(context, channel_twitch_id)


@router.get("/channels/{channel_twitch_id}/items/{item_id}")
def get_item(
    channel_twitch_id: str,
    item_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.get_item(context, channel_twitch_id, item_id)


@router.put("/channels/{channel_twitch_id}/items")
def upsert_item(
    channel_twitch_id: str,
    data: DiscordItemUpsertRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.upsert_item(context, channel_twitch_id, data)


@router.post("/channels/{channel_twitch_id}/items/{item_id}/archive")
def archive_item(
    channel_twitch_id: str,
    item_id: str,
    expected_version: int = Query(..., ge=1),
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.archive_item(context, channel_twitch_id, item_id, expected_version)


@router.get("/channels/{channel_twitch_id}/locations/{location_id}/item-drops")
def list_item_drops(
    channel_twitch_id: str,
    location_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
    item_weight: int | None = Query(default=None, ge=1, le=1_000_000),
    item_id: str | None = Query(default=None),
):
    if item_weight is not None:
        return service.preview_item_drop(
            context, channel_twitch_id, location_id, item_weight, item_id=item_id
        )
    return service.list_item_drops(context, channel_twitch_id, location_id)


@router.put("/channels/{channel_twitch_id}/locations/{location_id}/item-drops")
def upsert_item_drop(
    channel_twitch_id: str,
    location_id: str,
    data: ItemDropUpsertRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.upsert_item_drop(context, channel_twitch_id, location_id, data)


@router.delete(
    "/channels/{channel_twitch_id}/locations/{location_id}/item-drops/{item_id}"
)
def remove_item_drop(
    channel_twitch_id: str,
    location_id: str,
    item_id: str,
    expected_version: int = Query(..., ge=1),
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.remove_item_drop(
        context, channel_twitch_id, location_id, item_id, expected_version
    )


@router.get("/channels/{channel_twitch_id}/players/{viewer}/inventory")
def get_player_inventory(
    channel_twitch_id: str,
    viewer: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.get_player_inventory_admin(context, channel_twitch_id, viewer)


@router.post("/channels/{channel_twitch_id}/players/{viewer}/items")
def grant_player_item(
    channel_twitch_id: str,
    viewer: str,
    data: PlayerItemGrantRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.grant_player_item(context, channel_twitch_id, viewer, data)


@router.post(
    "/channels/{channel_twitch_id}/players/{viewer}/items/{inventory_item_id}/revoke"
)
def revoke_player_item(
    channel_twitch_id: str,
    viewer: str,
    inventory_item_id: int,
    data: PlayerItemRevokeRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.revoke_player_item(
        context,
        channel_twitch_id,
        viewer,
        inventory_item_id,
        data,
    )


@router.get("/channels/{channel_twitch_id}/players/{viewer}/modifiers")
def list_player_modifiers(
    channel_twitch_id: str,
    viewer: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.list_player_modifiers(context, channel_twitch_id, viewer)


@router.put("/channels/{channel_twitch_id}/players/{viewer}/modifiers")
def set_player_modifier(
    channel_twitch_id: str,
    viewer: str,
    data: PlayerModifierSetRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.set_player_modifier(
        context, channel_twitch_id, viewer, data
    )


@router.patch(
    "/channels/{channel_twitch_id}/players/{viewer}/modifiers/{modifier_id}/state"
)
def set_player_modifier_state(
    channel_twitch_id: str,
    viewer: str,
    modifier_id: str,
    data: VersionedStateRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.set_player_modifier_state(
        context, channel_twitch_id, viewer, modifier_id, data
    )


@router.delete(
    "/channels/{channel_twitch_id}/players/{viewer}/modifiers/{modifier_id}"
)
def remove_player_modifier(
    channel_twitch_id: str,
    viewer: str,
    modifier_id: str,
    expected_version: int = Query(..., ge=1),
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.remove_player_modifier(
        context,
        channel_twitch_id,
        viewer,
        modifier_id,
        expected_version,
    )


@router.get("/channels/{channel_twitch_id}/players/{viewer}/stats/explain")
def explain_player_stats(
    channel_twitch_id: str,
    viewer: str,
    scope: ModifierScope = Query(ModifierScope.FISHING),
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.explain_player_stats(
        context, channel_twitch_id, viewer, scope
    )


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


@router.get("/channels/{channel_twitch_id}/messages")
def list_messages(
    channel_twitch_id: str,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.get_messages(context, channel_twitch_id)


@router.patch("/channels/{channel_twitch_id}/messages/{message_key}")
def patch_message(
    channel_twitch_id: str,
    message_key: str,
    data: MessageTemplatePatchRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.patch_message(context, channel_twitch_id, message_key, data)


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


@router.post("/channels/{channel_twitch_id}/locations/{location_id}/rewards/import-legacy")
def import_legacy_rewards(
    channel_twitch_id: str,
    location_id: str,
    data: LegacyRewardImportRequest,
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.import_legacy_rewards(context, channel_twitch_id, location_id, data)


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


@router.get("/channels/{channel_twitch_id}/fishing-casts")
def list_recent_casts(
    channel_twitch_id: str,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    user_twitch_id: str | None = Query(None),
    status: str | None = Query(None),
    location_id: str | None = Query(None),
    reward_type: str | None = Query(None),
    start: str | None = Query(None),
    end: str | None = Query(None),
    username: str | None = Query(None),
    event_id: int | None = Query(None),
    item_id: str | None = Query(None),
    has_item: bool | None = Query(None),
    min_mass_delta: float | None = Query(None),
    max_mass_delta: float | None = Query(None),
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.list_recent_casts(
        context,
        channel_twitch_id,
        limit=limit,
        cursor=cursor,
        user_twitch_id=user_twitch_id,
        status=status,
        location_id=location_id,
        reward_type=reward_type,
        start=start,
        end=end,
        username=username,
        event_id=event_id,
        item_id=item_id,
        has_item=has_item,
        min_mass_delta=min_mass_delta,
        max_mass_delta=max_mass_delta,
    )


@router.get("/channels/{channel_twitch_id}/fishing-casts/{cast_id}")
def get_cast_detail(
    channel_twitch_id: str,
    cast_id: str,
    include_technical: bool = Query(False),
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.get_cast_detail(
        context, channel_twitch_id, cast_id, include_technical=include_technical
    )


@router.get("/channels/{channel_twitch_id}/fishing-stats/summary")
def get_cast_summary_stats(
    channel_twitch_id: str,
    start: str | None = Query(None),
    end: str | None = Query(None),
    context: DiscordServiceContext = Depends(get_discord_service_context),
    service: DiscordAdminService = Depends(get_discord_admin_service),
):
    return service.get_cast_summary_stats(
        context, channel_twitch_id, start=start, end=end
    )


# ruff: noqa: B008
