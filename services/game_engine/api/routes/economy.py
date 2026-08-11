from fastapi import APIRouter, Depends, Header, HTTPException

from api.dependencies import get_economy_service, verify_security
from domain.schemas.fishing import FishRequest, FishResponse
from services.economy_service import EconomyService
from domain.economy import EconomyDomainError


router = APIRouter()


def _resolve_real_user_id(auth_id: str, request_user_id: str) -> str:
    if auth_id == "BOT_SERVICE":
        return request_user_id
    if auth_id != request_user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    return auth_id


@router.post("/fishsell", response_model=FishResponse)
async def fishsell(
    request: FishRequest,
    service: EconomyService = Depends(get_economy_service),
    auth_id: str = Depends(verify_security),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    real_user_id = _resolve_real_user_id(auth_id, request.user_id)
    try:
        if not idempotency_key:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "IDEMPOTENCY_KEY_REQUIRED",
                    "message": "Idempotency-Key is required",
                },
            )
        return await service.sell_fish(
            twitch_id=real_user_id,
            channel_id=request.channel_id,
            amount_str=request.user_input,
            idempotency_key=idempotency_key,
            source_request_id=request.source_request_id,
        )
    except EconomyDomainError as error:
        raise HTTPException(
            status_code=400, detail={"code": error.code, "message": error.message}
        ) from error


@router.post("/fishbuy", response_model=FishResponse)
async def fishbuy(
    request: FishRequest,
    service: EconomyService = Depends(get_economy_service),
    auth_id: str = Depends(verify_security),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    real_user_id = _resolve_real_user_id(auth_id, request.user_id)
    try:
        if not idempotency_key:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "IDEMPOTENCY_KEY_REQUIRED",
                    "message": "Idempotency-Key is required",
                },
            )
        return await service.buy_fish(
            twitch_id=real_user_id,
            channel_id=request.channel_id,
            amount_str=request.user_input,
            idempotency_key=idempotency_key,
            source_request_id=request.source_request_id,
        )
    except EconomyDomainError as error:
        raise HTTPException(
            status_code=400, detail={"code": error.code, "message": error.message}
        ) from error


@router.get("/fishrate/{channel_id}")
def fishrate(channel_id: str, service: EconomyService = Depends(get_economy_service)):
    try:
        return service.rate(channel_id)
    except EconomyDomainError as error:
        raise HTTPException(
            status_code=404, detail={"code": error.code, "message": error.message}
        ) from error
