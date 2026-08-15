"""Least-privilege control-plane API used by the Twitch bot gateway."""

# FastAPI evaluates dependency factories at request time.
# ruff: noqa: B008

import json
from datetime import datetime, timezone
from typing import Any

from api.dependencies import get_db
from api.internal_dependencies import require_twitch_bot_service
from core import metrics
from fastapi import APIRouter, Depends
from infrastructure.models import Channel
from infrastructure.redis_client import RedisClient
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session


router = APIRouter(
    prefix="/internal/twitch-bot",
    dependencies=[Depends(require_twitch_bot_service)],
)


class TwitchChannelStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    twitch_id: str = Field(..., min_length=1, max_length=120)
    login: str = Field(..., min_length=1, max_length=120)
    desired: str = Field(..., pattern="^(joined|parted)$")
    actual: str = Field(..., pattern="^(joined|parted|joining|leaving|unknown)$")
    last_error: str | None = Field(None, max_length=500)


class TwitchBotStatusReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_id: str = Field(..., min_length=1, max_length=120)
    reported_at: datetime
    channels: list[TwitchChannelStatus] = Field(default_factory=list, max_length=500)


@router.get("/channels")
def desired_channels(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = (
        db.query(Channel)
        .filter(Channel.twitch_bot_enabled.is_(True), Channel.is_active.is_(True))
        .order_by(Channel.id.asc())
        .all()
    )
    revision_value = max((row.bot_membership_updated_at for row in rows), default=None)
    revision = (
        revision_value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if revision_value
        else "empty"
    )
    metrics.set_gauge("twitch_bot_desired_channels", len(rows))
    return {
        "revision": revision,
        "channels": [
            {
                "channel_id": row.id,
                "twitch_id": row.twitch_id,
                "login": row.name or row.twitch_id,
            }
            for row in rows
        ],
    }


@router.post("/status")
def report_status(
    report: TwitchBotStatusReport,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    redis = RedisClient.get_client()
    reported_at = report.reported_at.astimezone(timezone.utc).isoformat()
    redis.setex(
        f"fish:twitch-bot:instance:{report.instance_id}",
        90,
        json.dumps(
            {
                "instance_id": report.instance_id,
                "reported_at": reported_at,
                "channel_count": len(report.channels),
            }
        ),
    )
    for item in report.channels:
        channel = db.query(Channel).filter(Channel.twitch_id == item.twitch_id).first()
        if not channel:
            continue
        payload = {
            "desired": item.desired,
            "actual": item.actual,
            "login": item.login,
            "instance_id": report.instance_id,
            "joined_at": reported_at if item.actual == "joined" else None,
            "last_checked_at": reported_at,
            "last_error": item.last_error,
        }
        redis.setex(
            f"fish:twitch-bot:channel:{item.twitch_id}",
            90,
            json.dumps(payload),
        )
    metrics.set_gauge(
        "twitch_bot_joined_channels",
        sum(item.actual == "joined" for item in report.channels),
    )
    return {"status": "accepted", "reported_at": reported_at}
