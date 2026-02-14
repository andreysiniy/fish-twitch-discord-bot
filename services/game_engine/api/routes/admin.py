from fastapi import APIRouter, Depends, HTTPException
from typing import List

from services.admin_service import AdminService
from api.dependencies import get_admin_service, get_current_user_id
from domain.schemas.admin import (
    ChannelAccessResponseDTO,
    ChannelAccessUpsertDTO,
    ChannelCreateDTO, 
    ChannelResponseDTO, 
    RewardPoolUpdateDTO,
    RewardPoolResponseDTO,
    PlayerListResponse
)

router = APIRouter()

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


@router.get("/channels/{channel_twitch_id}/moderators", response_model=List[ChannelAccessResponseDTO])
def list_channel_moderators(
    channel_twitch_id: str,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        return service.list_channel_access(current_user_id, channel_twitch_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/channels/{channel_twitch_id}/moderators", response_model=ChannelAccessResponseDTO)
def upsert_channel_moderator(
    channel_twitch_id: str,
    data: ChannelAccessUpsertDTO,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        return service.upsert_channel_access(current_user_id, channel_twitch_id, data)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/channels/{channel_twitch_id}/moderators/{user_twitch_id}")
def remove_channel_moderator(
    channel_twitch_id: str,
    user_twitch_id: str,
    current_user_id: str = Depends(get_current_user_id),
    service: AdminService = Depends(get_admin_service)
):
    try:
        service.remove_channel_access(current_user_id, channel_twitch_id, user_twitch_id)
        return {"status": "ok"}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
