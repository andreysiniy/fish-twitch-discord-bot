from fastapi import APIRouter, Depends, HTTPException
from services.fishing_service import FishingService
from api.dependencies import get_fishing_service
from domain.schemas.fishing import FishRequest, FishResponse

router = APIRouter()

@router.post("/fish", response_model=FishResponse)
def cast_rod(
    request: FishRequest,
    service: FishingService = Depends(get_fishing_service)
):
    try:
        result = service.process_cast(
            twitch_id=request.user_id,
            username=request.username,
            channel_id=request.channel_id
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))