from fastapi import APIRouter, Depends, HTTPException
from services.inventory_service import InventoryService
from api.dependencies import get_inventory_service
from domain.schemas.rpg import EquipRequestDTO, EquipResponseDTO, InventoryDTO

router = APIRouter()

@router.post("/equip", response_model=EquipResponseDTO)
def equip_item(
    request: EquipRequestDTO,
    service: InventoryService = Depends(get_inventory_service)
):
    return service.equip_item(request)

@router.get("/{channel_id}/{user_id}", response_model=InventoryDTO)
def get_inventory(
    channel_id: str,
    user_id: str,
    service: InventoryService = Depends(get_inventory_service)
):
    return service.get_inventory_msg(user_id, channel_id)