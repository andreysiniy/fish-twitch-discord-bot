from fastapi import APIRouter, Depends, HTTPException
from services.fishing_service import FishingService
from services.travel_service import TravelService
from api.dependencies import get_fishing_service, get_travel_service, verify_security
from domain.schemas.fishing import FishRequest, FishResponse, FishTravelRequest, FishTravelResponse

router = APIRouter()

@router.post("/fish", response_model=FishResponse)
def cast_rod(
    request: FishRequest,
    service: FishingService = Depends(get_fishing_service),
    auth_id: str = Depends(verify_security)
):
    print(f"Auth ID: {auth_id}, Request User ID: {request.user_id}")
    real_user_id = request.user_id
    if auth_id != "BOT_SERVICE":
        if auth_id != request.user_id:
            raise HTTPException(status_code=403, detail="Forbidden")
        real_user_id = auth_id
    try:
        result = service.process_cast(
            twitch_id=real_user_id,
            username=request.username,
            channel_id=request.channel_id,
            is_mod=request.is_mod,
            is_sub=request.is_sub
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

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
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
