from fastapi import APIRouter, Depends, HTTPException
from typing import List

from services.admin_service import AdminService
from api.dependencies import get_admin_service, get_current_user_id, verify_security
from domain.schemas.admin import (
    ChannelAccessListRequestDTO,
    ChannelAccessManageRequestDTO,
    ChannelAccessRemoveRequestDTO,
    ChannelAccessResponseDTO,
    ChannelAccessUpsertDTO,
    FishCooldownSetRequestDTO,
    FishCooldownSetResponseDTO,
    ChannelCreateDTO, 
    ChannelResponseDTO, 
    ItemDefinitionCreateDTO,
    ItemDefinitionResponseDTO,
    GrantItemRequestDTO,
    GrantItemResponseDTO,
    RewardPoolUpdateDTO,
    RewardPoolResponseDTO,
    PlayerListResponse
)
from domain.schemas.rpg import InventoryDTO

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
def list_channels(service: AdminService = Depends(get_admin_service)):
    return service.get_channels()


@router.put("/rewards/{twitch_id}/{location_id}", response_model=RewardPoolResponseDTO)
def update_rewards(
    twitch_id: str,
    location_id: str,
    data: RewardPoolUpdateDTO,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        pool = service.update_channel_rewards(current_user_id, twitch_id, location_id, data)
        return pool
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
    print(f"[AdminAPI] list_channel_moderators called by {current_user_id} for channel {channel_twitch_id}")
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

@router.post("/channels/{channel_twitch_id}/fishcd/set", response_model=FishCooldownSetResponseDTO)
def set_channel_fish_cooldown(
    channel_twitch_id: str,
    data: FishCooldownSetRequestDTO,
    security_subject: str = Depends(verify_security),
    service: AdminService = Depends(get_admin_service)
):
    print(f"[AdminAPI] set_channel_fish_cooldown called by {security_subject} for channel {channel_twitch_id} with seconds={data.seconds} and scope={data.scope}")
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
        return service.upsert_item_definition(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/items/definitions", response_model=List[ItemDefinitionResponseDTO])
def list_item_definitions(
    skip: int = 0,
    limit: int = 200,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    return service.list_item_definitions(skip=skip, limit=limit)


@router.post("/items/grant", response_model=GrantItemResponseDTO)
def grant_item_to_player(
    data: GrantItemRequestDTO,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        item = service.grant_item_to_player(current_user_id, data)
        definition = item.definition
        response_item = {
            "item_id": item.item_id,
            "name": definition.name if definition else item.item_id,
            "description": definition.description if definition else None,
            "rarity": definition.rarity if definition else "common",
            "type": definition.type if definition else "fish",
            "image_url": definition.image_url if definition else None,
            "stats": definition.base_stats if definition else {},
            "quantity": item.quantity,
            "slot_id": item.slot_id,
            "current_durability": item.current_durability,
            "obtained_at": (item.meta or {}).get("obtained_at")
        }
        return {
            "success": True,
            "message": f"Granted {response_item['name']} x{response_item['quantity']} to user {data.user_twitch_id}.",
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
