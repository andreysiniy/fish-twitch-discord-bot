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
from infrastructure.models import (
    EconomyOperation,
    EconomyOperationEvent,
    EconomyProviderAttempt,
    FishingCast,
    OutboxEvent,
    UserProgress,
)
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
                "location_id": cast.location_id,
                "reward_type": cast.reward_type,
                "reward_id": cast.reward_id,
                "rng_trace": cast.rng_trace,
                "special_result": cast.special_result,
                "item_drop": cast.result_snapshot.get("item_drop")
                if isinstance(cast.result_snapshot, dict)
                else None,
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
                "attempts": operation.attempts,
                "external_applied": operation.external_applied,
                "provider_status_code": operation.provider_status_code,
                "provider_balance_before": operation.provider_balance_before,
                "provider_balance_after": operation.provider_balance_after,
            }
        )
        result["operation_events"] = [
            {
                "sequence_no": event.sequence_no,
                "event_type": event.event_type,
                "from_state": event.from_state,
                "to_state": event.to_state,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in (
                db.query(EconomyOperationEvent)
                .filter(EconomyOperationEvent.operation_id == operation.id)
                .order_by(EconomyOperationEvent.sequence_no.asc())
                .all()
            )
        ]
        result["provider_attempts"] = [
            {
                "attempt_no": attempt.attempt_no,
                "request_kind": attempt.request_kind,
                "outcome": attempt.outcome,
                "http_status": attempt.http_status,
                "error_code": attempt.error_code,
            }
            for attempt in (
                db.query(EconomyProviderAttempt)
                .filter(EconomyProviderAttempt.operation_id == operation.id)
                .order_by(EconomyProviderAttempt.attempt_no.asc())
                .all()
            )
        ]
        outbox = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.idempotency_key == f"economy:{operation.id}")
            .first()
        )
        result["outbox"] = (
            {
                "state": outbox.state,
                "attempts": outbox.attempts,
                "last_error": outbox.last_error,
            }
            if outbox
            else None
        )
        progress = (
            db.query(UserProgress)
            .filter(UserProgress.id == operation.user_id)
            .first()
        )
        result["current_mass"] = str(progress.current_mass) if progress else None
    return result


@router.get("/recent", dependencies=[Depends(require_testing_api)])
def recent_evidence(
    channel_id: int = Query(ge=1),
    twitch_user_id: str = Query(min_length=1, max_length=120),
    login: str = Query(min_length=1, max_length=120),
    since: float = Query(ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Locate evidence when Twitch IRC does not expose the outgoing message ID.

    TwitchIO 2.10's ``Channel.send`` and PRIVMSG echo do not carry a message
    ID.  The runner therefore uses the actor identity and send timestamp to
    discover the durable source request, then fetches its full evidence using
    ``/evidence``.  This endpoint is test-only and read-only.
    """

    since_at = datetime.fromtimestamp(since, tz=timezone.utc)
    casts = (
        db.query(FishingCast)
        .filter(
            FishingCast.channel_id == channel_id,
            FishingCast.twitch_user_id_snapshot == twitch_user_id,
            FishingCast.requested_at >= since_at,
        )
        .all()
    )
    operations = (
        db.query(EconomyOperation)
        .filter(
            EconomyOperation.channel_id == channel_id,
            EconomyOperation.twitch_username == login.lower(),
            EconomyOperation.requested_at >= since_at,
        )
        .all()
    )
    items = [
        {
            "kind": "cast",
            "id": str(row.id),
            "source_request_id": row.source_request_id,
            "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        }
        for row in casts
    ]
    items.extend(
        {
            "kind": "economy",
            "id": str(row.id),
            "source_request_id": row.source_request_id,
            "requested_at": row.requested_at.isoformat() if row.requested_at else None,
        }
        for row in operations
    )
    items.sort(key=lambda item: item["requested_at"] or "")
    return {"items": items}


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
