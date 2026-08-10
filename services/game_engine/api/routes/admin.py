from typing import List

from api.dependencies import get_admin_service, get_current_user_id, verify_security
from domain.schemas.admin import (
    ChannelAccessListRequestDTO,
    ChannelAccessManageRequestDTO,
    ChannelAccessRemoveRequestDTO,
    ChannelAccessResponseDTO,
    ChannelAccessUpsertDTO,
    ChannelCreateDTO,
    ChannelResponseDTO,
    FishCooldownSetRequestDTO,
    FishCooldownSetResponseDTO,
    FishingEventCreateRequestDTO,
    FishingEventDeleteRequestDTO,
    FishingEventListRequestDTO,
    FishingEventListResponseDTO,
    FishingEventResponseDTO,
    FishingEventToggleRequestDTO,
    FishingEventToggleResponseDTO,
    FishingEventUpdateRequestDTO,
    GrantItemRequestDTO,
    GrantItemResponseDTO,
    ItemDefinitionCreateDTO,
    ItemDefinitionResponseDTO,
    PlayerListResponse,
    RewardPoolResponseDTO,
    RewardPoolUpdateDTO,
    StreamElementsIntegrationResponseDTO,
    StreamElementsIntegrationUpsertDTO,
)
from domain.schemas.rpg import InventoryDTO
from fastapi import APIRouter, Depends, HTTPException
from services.admin_service import AdminService

router = APIRouter()


def _resolve_actor_twitch_id(security_subject: str, actor_twitch_id: str | None) -> str:
    if security_subject == "BOT_SERVICE":
        if not actor_twitch_id:
            raise HTTPException(status_code=401, detail="Missing actor_twitch_id in request body")
        return actor_twitch_id
    return security_subject

@router.post("/channels", response_model=ChannelResponseDTO)
def register_channel(
    data: ChannelCreateDTO, 
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    if data.twitch_id != current_user_id:
        raise HTTPException(status_code=403, detail="Channel can only be created for current user")
    try:
        return service.create_channel(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/channels", response_model=List[ChannelResponseDTO])
def list_channels(
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service),
):
    return service.get_channels(current_user_id)


@router.post(
    "/channels/{channel_twitch_id}/streamelements",
    response_model=StreamElementsIntegrationResponseDTO
)
async def upsert_streamelements_integration(
    channel_twitch_id: str,
    data: StreamElementsIntegrationUpsertDTO,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        return await service.upsert_stream_elements_integration(
            requester_twitch_id=current_user_id,
            channel_twitch_id=channel_twitch_id,
            se_token=data.se_token
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        status = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail)


@router.put("/rewards/{twitch_id}/{location_id}", response_model=RewardPoolResponseDTO)
def update_rewards(
    twitch_id: str,
    location_id: str,
    data: RewardPoolUpdateDTO,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        service.update_channel_rewards(current_user_id, twitch_id, location_id, data)
        return service.get_channel_rewards(current_user_id, twitch_id, location_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/rewards/{twitch_id}/{location_id}", response_model=RewardPoolResponseDTO)
def get_rewards(
    twitch_id: str,
    location_id: str,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        return service.get_channel_rewards(current_user_id, twitch_id, location_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/players/{channel_twitch_id}", response_model=PlayerListResponse)
def get_channel_players(
    channel_twitch_id: str,
    skip: int = 0,
    limit: int = 50,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        return service.get_players(current_user_id, channel_twitch_id, skip, limit)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/channels/{channel_twitch_id}/moderators/list", response_model=List[ChannelAccessResponseDTO])
def list_channel_moderators(
    channel_twitch_id: str,
    data: ChannelAccessListRequestDTO,
    security_subject: str = Depends(verify_security),
    service: AdminService = Depends(get_admin_service)
):
    current_user_id = _resolve_actor_twitch_id(security_subject, data.actor_twitch_id)
    try:
        return service.list_channel_access(current_user_id, channel_twitch_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/channels/{channel_twitch_id}/moderators/upsert", response_model=ChannelAccessResponseDTO)
def upsert_channel_moderator(
    channel_twitch_id: str,
    data: ChannelAccessManageRequestDTO,
    security_subject: str = Depends(verify_security),
    service: AdminService = Depends(get_admin_service)
):
    current_user_id = _resolve_actor_twitch_id(security_subject, data.actor_twitch_id)
    upsert_data = ChannelAccessUpsertDTO(
        user_twitch_id=data.user_twitch_id,
        user_twitch_name=data.user_twitch_name,
        role=data.role
    )
    try:
        return service.upsert_channel_access(current_user_id, channel_twitch_id, upsert_data)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/channels/{channel_twitch_id}/moderators/remove")
def remove_channel_moderator(
    channel_twitch_id: str,
    data: ChannelAccessRemoveRequestDTO,
    security_subject: str = Depends(verify_security),
    service: AdminService = Depends(get_admin_service)
):
    current_user_id = _resolve_actor_twitch_id(security_subject, data.actor_twitch_id)
    try:
        service.remove_channel_access(current_user_id, channel_twitch_id, data.user_twitch_id)
        return {"status": "ok"}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/channels/{channel_twitch_id}/events/list", response_model=FishingEventListResponseDTO)
def list_fishing_events(
    channel_twitch_id: str,
    data: FishingEventListRequestDTO,
    security_subject: str = Depends(verify_security),
    service: AdminService = Depends(get_admin_service)
):
    current_user_id = _resolve_actor_twitch_id(security_subject, data.actor_twitch_id)
    try:
        return service.list_fishing_events(current_user_id, channel_twitch_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/legacy/channels/{channel_twitch_id}/events", response_model=FishingEventResponseDTO)
def create_fishing_event(
    channel_twitch_id: str,
    data: FishingEventCreateRequestDTO,
    security_subject: str = Depends(verify_security),
    service: AdminService = Depends(get_admin_service)
):
    current_user_id = _resolve_actor_twitch_id(security_subject, data.actor_twitch_id)
    try:
        return service.create_fishing_event(current_user_id, channel_twitch_id, data)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        status = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail)


@router.put("/legacy/channels/{channel_twitch_id}/events/{event_id}", response_model=FishingEventResponseDTO)
def update_fishing_event(
    channel_twitch_id: str,
    event_id: int,
    data: FishingEventUpdateRequestDTO,
    security_subject: str = Depends(verify_security),
    service: AdminService = Depends(get_admin_service)
):
    current_user_id = _resolve_actor_twitch_id(security_subject, data.actor_twitch_id)
    try:
        return service.update_fishing_event(current_user_id, channel_twitch_id, event_id, data)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        status = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail)


@router.delete("/legacy/channels/{channel_twitch_id}/events/{event_id}")
def delete_fishing_event(
    channel_twitch_id: str,
    event_id: int,
    data: FishingEventDeleteRequestDTO,
    security_subject: str = Depends(verify_security),
    service: AdminService = Depends(get_admin_service)
):
    current_user_id = _resolve_actor_twitch_id(security_subject, data.actor_twitch_id)
    try:
        service.delete_fishing_event(current_user_id, channel_twitch_id, event_id)
        return {"status": "ok"}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/channels/{channel_twitch_id}/events/toggle", response_model=FishingEventToggleResponseDTO)
def toggle_fishing_event(
    channel_twitch_id: str,
    data: FishingEventToggleRequestDTO,
    security_subject: str = Depends(verify_security),
    service: AdminService = Depends(get_admin_service)
):
    current_user_id = _resolve_actor_twitch_id(security_subject, data.actor_twitch_id)
    try:
        return service.toggle_fishing_event(
            requester_twitch_id=current_user_id,
            channel_twitch_id=channel_twitch_id,
            event_id=data.event_number,
            duration_seconds=data.duration_seconds
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        status = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail)

@router.post("/channels/{channel_twitch_id}/fishcd/set", response_model=FishCooldownSetResponseDTO)
def set_channel_fish_cooldown(
    channel_twitch_id: str,
    data: FishCooldownSetRequestDTO,
    security_subject: str = Depends(verify_security),
    service: AdminService = Depends(get_admin_service)
):
    current_user_id = _resolve_actor_twitch_id(security_subject, data.actor_twitch_id)
    try:
        return service.set_fishing_cooldown(
            requester_twitch_id=current_user_id,
            channel_twitch_id=channel_twitch_id,
            seconds=data.seconds,
            scope=data.scope
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        status = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status, detail=detail)


@router.post("/items/definitions", response_model=ItemDefinitionResponseDTO)
def upsert_item_definition(
    data: ItemDefinitionCreateDTO,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        return service.upsert_item_definition(requester_twitch_id=current_user_id, data=data)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/items/definitions", response_model=List[ItemDefinitionResponseDTO])
def list_item_definitions(
    skip: int = 0,
    limit: int = 200,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        return service.list_item_definitions(requester_twitch_id=current_user_id, skip=skip, limit=limit)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/items/grant", response_model=GrantItemResponseDTO)
def grant_item_to_player(
    data: GrantItemRequestDTO,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        item = service.grant_item_to_player(current_user_id, data)
        definition = item.definition
        logical_item_id = definition.item_id if definition else item.item_id
        response_item = {
            "id": item.id,
            "item_id": logical_item_id,
            "title": definition.title if definition else logical_item_id,
            "description": definition.description if definition else None,
            "rarity": definition.rarity if definition else "common",
            "item_type": definition.type if definition else "collectible",
            "equipment_slot": definition.slot if definition else None,
            "max_durability": definition.max_durability if definition else None,
            "max_charges": definition.max_charges if definition else None,
            "break_policy": definition.break_policy if definition else "indestructible",
            "stack_size": definition.stack_size if definition else 1,
            "image_url": definition.image_url if definition else None,
            "effects": definition.effects if definition else [],
            "definition_version": item.definition_version,
            "obtained_definition_version": getattr(
                item, "obtained_definition_version", item.definition_version
            ),
            "quantity": item.quantity,
            "slot_id": item.slot_id,
            "current_durability": item.current_durability,
            "current_charges": item.current_charges,
            "obtained_at": (item.meta or {}).get("obtained_at"),
            "version": item.version,
            "meta": item.meta or {},
        }
        return {
            "success": True,
            "message": f"Granted {response_item['title']} x{response_item['quantity']} to user {data.user_twitch_id}.",
            "item": response_item
        }
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/players/{channel_twitch_id}/{user_twitch_id}/inventory", response_model=InventoryDTO)
def get_player_inventory(
    channel_twitch_id: str,
    user_twitch_id: str,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        return service.get_player_inventory(current_user_id, channel_twitch_id, user_twitch_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
