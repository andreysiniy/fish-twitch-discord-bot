"""Read-side queries for the fishing cast ledger (admin history, search, stats)."""

from datetime import datetime, timezone
from typing import Any

from infrastructure.models import FishingCast
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload


class FishingCastQueryRepository:
    def __init__(self, db: Session):
        self.db = db

    def recent_casts(
        self,
        *,
        channel_id: int,
        limit: int = 20,
        cursor: str | None = None,
        user_progress_id: int | None = None,
        status: str | None = None,
        location_id: str | None = None,
        reward_type: str | None = None,
    ) -> tuple[list[FishingCast], str | None]:
        """Return (casts, next_cursor) ordered by (requested_at desc, id desc).

        ``cursor`` encodes the last row's ``(requested_at, id)`` so pagination is
        a stable keyset and never re-scans the full table.
        """
        query = self.db.query(FishingCast).filter(FishingCast.channel_id == channel_id)
        if user_progress_id is not None:
            query = query.filter(FishingCast.user_progress_id == user_progress_id)
        if status:
            query = query.filter(FishingCast.status == status)
        if location_id:
            query = query.filter(FishingCast.location_id == location_id)
        if reward_type:
            query = query.filter(FishingCast.reward_type == reward_type)
        if cursor:
            anchor_requested_at, anchor_id = _decode_cursor(cursor)
            query = query.filter(
                (FishingCast.requested_at < anchor_requested_at)
                | (
                    (FishingCast.requested_at == anchor_requested_at)
                    & (FishingCast.id < anchor_id)
                )
            )
        query = query.order_by(
            FishingCast.requested_at.desc(), FishingCast.id.desc()
        ).limit(limit + 1)
        rows = query.all()
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = _encode_cursor(page[-1]) if has_more else None
        return page, next_cursor

    def get_cast(self, cast_id: str, channel_id: int) -> FishingCast | None:
        return (
            self.db.query(FishingCast)
            .options(joinedload(FishingCast.item_drops))
            .filter(
                FishingCast.id == cast_id,
                FishingCast.channel_id == channel_id,
            )
            .first()
        )

    def summary(
        self,
        *,
        channel_id: int,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Any]:
        query = self.db.query(FishingCast).filter(FishingCast.channel_id == channel_id)
        if start:
            query = query.filter(FishingCast.requested_at >= start)
        if end:
            query = query.filter(FishingCast.requested_at <= end)
        resolved = query.filter(FishingCast.status == "resolved").all()

        total_casts = len(resolved)
        items_expected = 0.0
        items_actual = 0
        mass_positive = 0
        mass_negative = 0
        total_xp = 0
        level_ups = 0
        for cast in resolved:
            items_expected += float(cast.item_drop_probability or 0)
            items_actual += int(cast.item_drop_count or 0)
            delta = float(cast.mass_delta_applied or 0)
            if delta >= 0:
                mass_positive += delta
            else:
                mass_negative += -delta
            total_xp += int(cast.xp_gained or 0)
            level_ups += 1 if cast.was_level_up else 0

        failures = (
            self.db.query(FishingCast)
            .filter(
                FishingCast.channel_id == channel_id,
                FishingCast.status.in_(["failed", "compensated"]),
            )
            .count()
        )
        unique_players = (
            self.db.query(func.count(func.distinct(FishingCast.user_progress_id)))
            .filter(FishingCast.channel_id == channel_id)
            .scalar()
            or 0
        )
        return {
            "casts": total_casts,
            "unique_players": unique_players,
            "failures": failures,
            "mass_positive": mass_positive,
            "mass_negative": mass_negative,
            "total_xp": total_xp,
            "level_ups": level_ups,
            "items_actual": items_actual,
            "items_expected": items_expected,
        }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _encode_cursor(cast: FishingCast) -> str:
    ts = cast.requested_at.isoformat() if cast.requested_at else ""
    return f"{ts}|{cast.id}"


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    ts, _, cast_id = cursor.partition("|")
    return datetime.fromisoformat(ts), cast_id
