import uuid

from fastapi import APIRouter, Depends, Header, HTTPException

from api.dependencies import get_external_action_service, verify_security
from domain.schemas.external_actions import ExternalActionRequest, ExternalActionResponse
from services.external_action_service import ExternalActionService


router = APIRouter()


@router.post("/execute", response_model=ExternalActionResponse)
def execute_external_action(
    data: ExternalActionRequest,
    security_subject: str = Depends(verify_security),
    service: ExternalActionService = Depends(get_external_action_service),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> ExternalActionResponse:
    if security_subject != "BOT_SERVICE":
        raise HTTPException(status_code=403, detail="Service credentials required")
    try:
        return service.queue(data, idempotency_key or str(uuid.uuid4()))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
