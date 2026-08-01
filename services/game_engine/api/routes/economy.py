import uuid

from fastapi import APIRouter, Depends, Header, HTTPException

from api.dependencies import get_economy_service, verify_security
from domain.schemas.fishing import FishRequest, FishResponse
from services.economy_service import EconomyService


router = APIRouter()


def _resolve_real_user_id(auth_id: str, request_user_id: str) -> str:
    if auth_id == "BOT_SERVICE":
        return request_user_id
    if auth_id != request_user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return auth_id


@router.post("/fishsell", response_model=FishResponse)
def fishsell(
    request: FishRequest,
    service: EconomyService = Depends(get_economy_service),
    auth_id: str = Depends(verify_security),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    real_user_id = _resolve_real_user_id(auth_id, request.user_id)
    try:
        return service.sell_fish(
            twitch_id=real_user_id,
            channel_id=request.channel_id,
            amount_str=request.user_input,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/fishbuy", response_model=FishResponse)
def fishbuy(
    request: FishRequest,
    service: EconomyService = Depends(get_economy_service),
    auth_id: str = Depends(verify_security),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    real_user_id = _resolve_real_user_id(auth_id, request.user_id)
    try:
        return service.buy_fish(
            twitch_id=real_user_id,
            channel_id=request.channel_id,
            amount_str=request.user_input,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
