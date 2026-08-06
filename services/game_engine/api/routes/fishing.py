from fastapi import APIRouter, Depends, HTTPException
from services.fishing_service import FishingService
from services.travel_service import TravelService
from api.dependencies import get_fishing_service, get_travel_service, verify_security
from domain.schemas.fishing import (
    FishRequest,
    FishResponse,
    FishCooldownRequest,
    FishCooldownResponse,
    FishTravelRequest,
    FishTravelResponse,
    FishStatsResponse,
    FishTopResponse,
)

router = APIRouter()

@router.post("/fish", response_model=FishResponse)
def cast_rod(
    request: FishRequest,
    service: FishingService = Depends(get_fishing_service),
    auth_id: str = Depends(verify_security)
):
    real_user_id = request.user_id
    if auth_id != "BOT_SERVICE":
        if auth_id != request.user_id:
            raise HTTPException(status_code=403, detail="Forbidden")
        real_user_id = auth_id
    try:
        return service.process_cast(
            twitch_id=real_user_id,
            username=request.username,
            channel_id=request.channel_id,
            is_mod=request.is_mod,
            is_sub=request.is_sub,
            bypass_cooldown=request.bypass_cooldown and auth_id == "BOT_SERVICE",
            source=request.source or "twitch",
            source_request_id=request.source_request_id,
            requested_at=request.requested_at,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

@router.post("/fishtravel", response_model=FishTravelResponse)
def fish_travel(
    request: FishTravelRequest,
    service: TravelService = Depends(get_travel_service),
    auth_id: str = Depends(verify_security)
):
    real_user_id = request.user_id
    if auth_id != "BOT_SERVICE":
        if auth_id != request.user_id:
            raise HTTPException(status_code=403, detail="Forbidden")
        real_user_id = auth_id
    try:
        request.user_id = real_user_id
        return service.process_travel(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/fishcd", response_model=FishCooldownResponse)
def fish_cooldown(
    request: FishCooldownRequest,
    service: FishingService = Depends(get_fishing_service),
    auth_id: str = Depends(verify_security)
):
    # Any authenticated caller can request cooldown for any user.
    if not auth_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not request.user_id or not request.username:
        raise HTTPException(status_code=400, detail="user_id and username are required")
    try:
        response = service.get_cooldown_status(
            twitch_id=request.user_id,
            username=request.username,
            channel_id=request.channel_id,
            is_mod=request.is_mod,
            is_sub=request.is_sub
        )
        return response
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/fishstats/{channel_id}/{user_id}", response_model=FishStatsResponse)
def fish_stats(
    channel_id: str,
    user_id: str,
    username: str | None = None,
    service: FishingService = Depends(get_fishing_service),
    auth_id: str = Depends(verify_security)
):
    # Any authenticated caller can request stats for any user.
    if not auth_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        return service.get_profile_stats(twitch_id=user_id, channel_id=channel_id, username=username)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/fishtop/{channel_id}", response_model=FishTopResponse)
def fish_top(
    channel_id: str,
    limit: int = 10,
    mode: str = "current",
    service: FishingService = Depends(get_fishing_service),
    auth_id: str = Depends(verify_security)
):
    if not auth_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    normalized_mode = (mode or "current").lower()
    if normalized_mode not in {"current", "alltime", "catches", "level"}:
        raise HTTPException(status_code=400, detail="Invalid mode. Use: current, alltime, catches, level")
    try:
        return service.get_channel_top(channel_id=channel_id, limit=max(1, min(limit, 25)), mode=normalized_mode)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
