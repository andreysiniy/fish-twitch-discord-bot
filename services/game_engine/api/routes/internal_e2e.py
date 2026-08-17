"""Read-only evidence and controlled fixtures for the dedicated E2E runner."""

# FastAPI dependency factories are evaluated at request time.
# ruff: noqa: B008

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from api.dependencies import get_db
from core.config import settings
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from infrastructure.models import EconomyOperation, FishingCast
from infrastructure.redis_client import RedisClient
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

router = APIRouter(prefix="/internal/e2e", tags=["Internal E2E"])
testing_router = APIRouter(prefix="/internal/testing", tags=["Internal Testing"])


def require_testing_api(x_e2e_service_key: str | None = Header(default=None)) -> None:
    if not settings.TESTING_API_ENABLED:
        raise HTTPException(status_code=404, detail="Testing API is disabled")
    if settings.TESTING_API_KEY and x_e2e_service_key != settings.TESTING_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid E2E service key")


class NextCastFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: str = Field(min_length=1, max_length=120)
    viewer_id: str = Field(min_length=1, max_length=120)
    outcome: str = Field(min_length=1, max_length=80)
    rng: dict[str, float] = Field(default_factory=dict)
    expires_in_seconds: int = Field(default=60, ge=1, le=3600)


@router.get("/evidence", dependencies=[Depends(require_testing_api)])
def evidence(
    source_request_id: str = Query(min_length=1, max_length=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    cast = (
        db.query(FishingCast)
        .filter(FishingCast.source_request_id == source_request_id)
        .order_by(FishingCast.requested_at.desc())
        .first()
    )
    operation = (
        db.query(EconomyOperation)
        .filter(EconomyOperation.source_request_id == source_request_id)
        .order_by(EconomyOperation.requested_at.desc())
        .first()
    )
    if cast is None and operation is None:
        raise HTTPException(status_code=404, detail="No evidence found")
    result: dict[str, Any] = {"source_request_id": source_request_id}
    if cast is not None:
        result["fishing_cast_id"] = str(cast.id)
        result.update(
            {
                "cast_status": cast.status,
                "mass_before": str(cast.mass_before),
                "mass_after": str(cast.mass_after),
                "mass_delta": str(cast.mass_delta_applied),
                "xp_before": cast.xp_before,
                "xp_after": cast.xp_after,
            }
        )
    if operation is not None:
        result.update(
            {
                "economy_operation_id": str(operation.id),
                "state": operation.state,
                "mass_delta": str(operation.mass_delta),
                "points_delta": str(operation.points_delta),
                "provider_channel_id_snapshot": operation.provider_channel_id_snapshot,
                "response_payload": operation.response_payload,
            }
        )
    return result


@testing_router.post("/next-cast", dependencies=[Depends(require_testing_api)])
def next_cast_fixture(payload: NextCastFixture) -> dict[str, Any]:
    fixture_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc).timestamp() + payload.expires_in_seconds
    key = f"fish:e2e:next-cast:{payload.channel_id}:{payload.viewer_id}"
    RedisClient.get_client().setex(
        key,
        payload.expires_in_seconds,
        json.dumps(
            {
                "fixture_id": fixture_id,
                "channel_id": payload.channel_id,
                "viewer_id": payload.viewer_id,
                "outcome": payload.outcome,
                "rng": payload.rng,
                "expires_at": expires_at,
            }
        ),
    )
    return {"fixture_id": fixture_id, "expires_at": expires_at}
