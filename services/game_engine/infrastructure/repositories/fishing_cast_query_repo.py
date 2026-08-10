"""Read-side queries for the fishing cast ledger (admin history, search, stats)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from domain.logic.rng import RARITY_RANK
from infrastructure.models import (
    FishingCast,
    FishingCastItemDrop,
    FishingRulesetSnapshot,
    FishingStatsDaily,
)
from sqlalchemy import Integer, func
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

        # Aggregations run in SQL; the resolved set is never loaded in full.
        resolved_filter = base.filter(FishingCast.status == "resolved")
        aggregate = (
            resolved_filter.with_entities(
                func.count(FishingCast.id),
                func.coalesce(func.sum(func.coalesce(FishingCast.item_drop_probability, 0)), 0),
                func.coalesce(func.sum(FishingCast.item_drop_count), 0),
                func.coalesce(
                    func.sum(
                        func.greatest(func.coalesce(FishingCast.mass_delta_applied, 0), 0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        func.greatest(
                            -func.coalesce(FishingCast.mass_delta_applied, 0), 0
                        )
                    ),
                    0,
                ),
                func.coalesce(func.sum(FishingCast.xp_gained), 0),
                func.coalesce(
                    func.sum(func.cast(FishingCast.was_level_up, Integer)), 0
                ),
            )
            .one()
        )
        total_casts = int(aggregate[0] or 0)
        items_expected = float(aggregate[1] or 0)
        items_actual = int(aggregate[2] or 0)
        mass_positive = float(aggregate[3] or 0)
        mass_negative = float(aggregate[4] or 0)
        total_xp = int(aggregate[5] or 0)
        level_ups = int(aggregate[6] or 0)

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

        # Item-specific buckets: casts that dropped an item also contribute to
        # a bucket keyed by that item, so the item dimension of the model is
        # actually populated (one bulk query, no N+1).
        cast_ids_with_drops = [
            cast.id for cast in rows if cast.status == "resolved" and cast.item_drop_count
        ]
        drops_by_cast: dict[Any, list[FishingCastItemDrop]] = {}
        if cast_ids_with_drops:
            for drop in (
                self.db.query(FishingCastItemDrop)
                .filter(FishingCastItemDrop.cast_id.in_(cast_ids_with_drops))
                .all()
            ):
                drops_by_cast.setdefault(drop.cast_id, []).append(drop)

        snapshot_ids = {
            cast.ruleset_snapshot_id for cast in rows if cast.ruleset_snapshot_id is not None
        }
        snapshots = {
            snapshot.id: snapshot.item_entries_snapshot or []
            for snapshot in self.db.query(FishingRulesetSnapshot)
            .filter(FishingRulesetSnapshot.id.in_(snapshot_ids))
            .all()
        }

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
                item_probabilities = self._item_expected_probabilities(
                    cast,
                    snapshots.get(cast.ruleset_snapshot_id, []),
                )
                drops = drops_by_cast.get(cast.id, [])
                drops_by_definition = {
                    drop.item_definition_id: drop for drop in drops
                }
                for item_definition_id, expected_probability in item_probabilities.items():
                    item_key = (
                        cast.channel_id,
                        cast.location_id,
                        cast.event_id,
                        cast.reward_type,
                        item_definition_id,
                    )
                    item_bucket = buckets.setdefault(
                        item_key,
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
                    item_bucket["casts"] += 1
                    item_bucket["players"].add(cast.user_progress_id)
                    item_bucket["item_drop_expected"] += float(expected_probability)
                    drop = drops_by_definition.get(item_definition_id)
                    if drop is not None:
                        if delta >= 0:
                            item_bucket["mass_positive"] += delta
                        else:
                            item_bucket["mass_negative"] += -delta
                        item_bucket["xp_gained"] += int(cast.xp_gained or 0)
                        item_bucket["item_drop_actual"] += int(
                            drop.quantity_granted or 0
                        )
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

        for (channel_id_, location_id_, event_id_, reward_type_, item_id_), data in buckets.items():
            self.db.add(
                FishingStatsDaily(
                    day=day_start,
                    channel_id=channel_id_,
                    location_id=location_id_,
                    event_id=event_id_,
                    reward_type=reward_type_,
                    item_definition_id=item_id_,
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

    @staticmethod
    def _item_expected_probabilities(
        cast: FishingCast,
        item_entries: list[dict[str, Any]],
    ) -> dict[int, Decimal]:
        """Return gate × selection probability for every item entry.

        The denominator is the complete eligible item table captured for the
        cast, so casts without a drop still contribute expected probability.
        """
        gate = Decimal(str(cast.item_drop_probability or 0))
        if gate <= 0 or not item_entries:
            return {}
        raw_luck = (cast.resolved_modifiers or {}).get("item_rarity_luck_pct", "0")
        luck = max(Decimal("1") + Decimal(str(raw_luck or 0)), Decimal("0.05"))
        weighted: list[tuple[int, Decimal]] = []
        for entry in item_entries:
            definition_id = entry.get("item_definition_id")
            if definition_id is None:
                continue
            remaining = entry.get("remaining_stock")
            if remaining is not None and int(remaining) <= 0:
                continue
            weight = Decimal(str(entry.get("weight") or 0))
            rarity_rank = RARITY_RANK.get(str(entry.get("rarity", "common")).lower(), 0)
            effective_weight = weight * (luck ** rarity_rank)
            if effective_weight > 0:
                weighted.append((int(definition_id), effective_weight))
        total_weight = sum((weight for _, weight in weighted), Decimal("0"))
        if total_weight <= 0:
            return {}
        return {
            definition_id: gate * (weight / total_weight)
            for definition_id, weight in weighted
        }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _encode_cursor(cast: FishingCast) -> str:
    ts = cast.requested_at.isoformat() if cast.requested_at else ""
    return f"{ts}|{cast.id}"


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    ts, _, cast_id = cursor.partition("|")
    return datetime.fromisoformat(ts), cast_id
