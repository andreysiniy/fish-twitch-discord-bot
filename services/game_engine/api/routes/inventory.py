from api.dependencies import get_inventory_service, verify_security
from domain.schemas.rpg import (
    EquipRequestDTO,
    EquipResponseDTO,
    InventoryResponseDTO,
    TrashItemRequestDTO,
    TrashItemResponseDTO,
    UnequipRequestDTO,
    UseItemRequestDTO,
    UseItemResponseDTO,
)
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from services.idempotency_service import IdempotencyService
from services.inventory_service import InventoryService

router = APIRouter()

@router.post("/equip", response_model=EquipResponseDTO)
def equip_item(
    request: EquipRequestDTO,
    service: InventoryService = Depends(get_inventory_service),
    security_subject: str = Depends(verify_security),
):
    _assert_inventory_owner(security_subject, request.user_id)
    return service.equip_item(request)


@router.post("/unequip", response_model=EquipResponseDTO)
def unequip_item(
    request: UnequipRequestDTO,
    service: InventoryService = Depends(get_inventory_service),
    security_subject: str = Depends(verify_security),
):
    _assert_inventory_owner(security_subject, request.user_id)
    return service.unequip_item(request)


@router.post("/use", response_model=UseItemResponseDTO)
def use_item(
    request: UseItemRequestDTO,
    service: InventoryService = Depends(get_inventory_service),
    security_subject: str = Depends(verify_security),
):
    _assert_inventory_owner(security_subject, request.user_id)
    try:
        return service.use_item(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/trash", response_model=TrashItemResponseDTO)
def trash_item(
    request: TrashItemRequestDTO,
    http_request: Request,
    service: InventoryService = Depends(get_inventory_service),
    security_subject: str = Depends(verify_security),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    _assert_inventory_owner(security_subject, request.user_id)
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required")

    payload = request.model_dump(mode="json")
    response = IdempotencyService(service.user_repo.db).execute(
        actor_scope=f"twitch:{request.channel_id}:{request.user_id}",
        key=idempotency_key,
        action="inventory.trash",
        payload=payload,
        request_id=http_request.headers.get("X-Request-ID", ""),
        callback=lambda: service.trash_item(request).model_dump(mode="json"),
    )
    return TrashItemResponseDTO.model_validate(response)


@router.get("/{channel_id}/{user_id}", response_model=InventoryResponseDTO)
def get_inventory(
    channel_id: str,
    user_id: str,
    service: InventoryService = Depends(get_inventory_service),
    security_subject: str = Depends(verify_security),
):
    _assert_inventory_owner(security_subject, user_id)
    return service.get_inventory_msg(user_id, channel_id)


def _assert_inventory_owner(security_subject: str, user_id: str) -> None:
    if security_subject not in {"BOT_SERVICE", user_id}:
        raise HTTPException(status_code=403, detail="Forbidden")
