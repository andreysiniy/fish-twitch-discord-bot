from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List

from services.admin_service import AdminService
from api.dependencies import get_admin_service
from domain.schemas.admin import (
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
    service: AdminService = Depends(get_admin_service)
):
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
    service: AdminService = Depends(get_admin_service)
):
    try:
        pool = service.update_channel_rewards(twitch_id, location_id, data)
        return pool
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/rewards/{twitch_id}/{location_id}", response_model=RewardPoolResponseDTO)
def get_rewards(
    twitch_id: str,
    location_id: str,
    service: AdminService = Depends(get_admin_service)
):
    try:
        return service.get_channel_rewards(twitch_id, location_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/players/{channel_twitch_id}", response_model=PlayerListResponse)
def get_channel_players(
    channel_twitch_id: str,
    skip: int = 0,
    limit: int = 50,
    service: AdminService = Depends(get_admin_service)
):
    return service.get_players(channel_twitch_id, skip, limit)