"""Read-side queries for the fishing cast ledger (admin history, search, stats)."""

from datetime import datetime, timedelta, timezone
from typing import Any

from infrastructure.models import FishingCast, FishingCastItemDrop, FishingStatsDaily
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
        start: datetime | None = None,
        end: datetime | None = None,
        username: str | None = None,
        event_id: int | None = None,
        item_id: str | None = None,
        has_item: bool | None = None,
        min_mass_delta: float | None = None,
        max_mass_delta: float | None = None,
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
        if start:
            query = query.filter(FishingCast.requested_at >= start)
        if end:
            query = query.filter(FishingCast.requested_at <= end)
        if username:
            query = query.filter(FishingCast.username_snapshot.ilike(f"%{username}%"))
        if event_id is not None:
            query = query.filter(FishingCast.event_id == event_id)
        if has_item is not None:
            if has_item:
                query = query.filter(FishingCast.item_drop_count > 0)
            else:
                query = query.filter(FishingCast.item_drop_count == 0)
        if min_mass_delta is not None:
            query = query.filter(FishingCast.mass_delta_applied >= min_mass_delta)
        if max_mass_delta is not None:
            query = query.filter(FishingCast.mass_delta_applied <= max_mass_delta)
        if item_id:
            query = query.filter(
                FishingCast.item_drops.any(
                    FishingCastItemDrop.item_id_snapshot == item_id
                )
            )
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
        base = self.db.query(FishingCast).filter(FishingCast.channel_id == channel_id)
        if start:
            base = base.filter(FishingCast.requested_at >= start)
        if end:
            base = base.filter(FishingCast.requested_at <= end)
        resolved = base.filter(FishingCast.status == "resolved").all()

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

        rejected = (
            base.filter(
                FishingCast.status.in_(
                    ["cooldown_rejected", "validation_rejected", "failed", "compensated"]
                )
            ).count()
        )
        failures = base.filter(
            FishingCast.status.in_(["failed", "compensated"])
        ).count()
        unique_players = (
            self.db.query(func.count(func.distinct(FishingCast.user_progress_id)))
            .filter(
                FishingCast.channel_id == channel_id,
                FishingCast.status == "resolved",
                FishingCast.requested_at >= (start or datetime.min.replace(tzinfo=timezone.utc)),
                FishingCast.requested_at <= (end or datetime.max.replace(tzinfo=timezone.utc)),
            )
            .scalar()
            or 0
        )
        return {
            "casts": total_casts,
            "unique_players": unique_players,
            "rejected": rejected,
            "failures": failures,
            "mass_positive": mass_positive,
            "mass_negative": mass_negative,
            "total_xp": total_xp,
            "level_ups": level_ups,
            "items_actual": items_actual,
            "items_expected": items_expected,
        }

    def rebuild_daily_stats(self, day: datetime, channel_id: int | None = None) -> int:
        """Idempotently recompute daily aggregates for a UTC day.

        Deletes and rewrites the whole day per channel, so a rerun always
        converges to the same result. Returns number of buckets written.
        """
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        next_day = day_start + timedelta(days=1)

        query = self.db.query(FishingCast).filter(
            FishingCast.requested_at >= day_start,
            FishingCast.requested_at < next_day,
        )
        if channel_id is not None:
            query = query.filter(FishingCast.channel_id == channel_id)
        rows = query.all()

        buckets: dict[tuple, dict[str, Any]] = {}
        for cast in rows:
            key = (
                cast.channel_id,
                cast.location_id,
                cast.event_id,
                cast.reward_type,
                None,
            )
            bucket = buckets.setdefault(
                key,
                {
                    "casts": 0,
                    "players": set(),
                    "mass_positive": 0,
                    "mass_negative": 0,
                    "xp_gained": 0,
                    "item_drop_expected": 0.0,
                    "item_drop_actual": 0,
                    "failures": 0,
                },
            )
            bucket["casts"] += 1
            if cast.status == "resolved":
                bucket["players"].add(cast.user_progress_id)
                delta = float(cast.mass_delta_applied or 0)
                if delta >= 0:
                    bucket["mass_positive"] += delta
                else:
                    bucket["mass_negative"] += -delta
                bucket["xp_gained"] += int(cast.xp_gained or 0)
                bucket["item_drop_expected"] += float(cast.item_drop_probability or 0)
                bucket["item_drop_actual"] += int(cast.item_drop_count or 0)
            elif cast.status in ("failed", "compensated"):
                bucket["failures"] += 1

        # Delete the day's aggregates per channel then rewrite (idempotent).
        self.db.query(FishingStatsDaily).filter(
            FishingStatsDaily.day == day_start,
        ).filter(
            FishingStatsDaily.channel_id.in_(
                {key[0] for key in buckets} if buckets else {channel_id} if channel_id else {-1}
            )
        ).delete(synchronize_session=False)
        self.db.flush()

        for (channel_id_, location_id_, event_id_, reward_type_, _item), data in buckets.items():
            self.db.add(
                FishingStatsDaily(
                    day=day_start,
                    channel_id=channel_id_,
                    location_id=location_id_,
                    event_id=event_id_,
                    reward_type=reward_type_,
                    item_definition_id=None,
                    casts=data["casts"],
                    unique_players=len(data["players"]),
                    mass_positive=data["mass_positive"],
                    mass_negative=data["mass_negative"],
                    xp_gained=data["xp_gained"],
                    item_drop_expected=data["item_drop_expected"],
                    item_drop_actual=data["item_drop_actual"],
                    failures=data["failures"],
                )
            )
        self.db.flush()
        return len(buckets)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _encode_cursor(cast: FishingCast) -> str:
    ts = cast.requested_at.isoformat() if cast.requested_at else ""
    return f"{ts}|{cast.id}"


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    ts, _, cast_id = cursor.partition("|")
    return datetime.fromisoformat(ts), cast_id
