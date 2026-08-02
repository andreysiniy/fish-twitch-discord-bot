from fastapi import APIRouter, Depends, HTTPException
from services.inventory_service import InventoryService
from api.dependencies import get_inventory_service, verify_security
from domain.schemas.rpg import (
    EquipRequestDTO,
    EquipResponseDTO,
    InventoryResponseDTO,
    RepairRequestDTO,
    UnequipRequestDTO,
    UseItemRequestDTO,
    UseItemResponseDTO,
)

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


@router.post("/repair", response_model=EquipResponseDTO)
def repair_item(
    request: RepairRequestDTO,
    service: InventoryService = Depends(get_inventory_service),
    security_subject: str = Depends(verify_security),
):
    _assert_inventory_owner(security_subject, request.user_id)
    return service.repair_item(request)


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
