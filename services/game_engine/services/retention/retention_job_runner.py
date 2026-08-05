"""Configurable retention cleanup for the fishing cast ledger.

Runs on an interval in the worker process and deletes only expired records that
the deployment policy has elected to age out. Resolved casts default to 24
months, rejected attempts to a shorter window, and expired idempotency rows are
cleaned daily as recommended by the roll-out policy.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from core.config import settings
from infrastructure.database import SessionLocal
from infrastructure.models import FishingCast, IdempotencyRecord

logger = logging.getLogger(__name__)

REJECTED_STATUSES = (
    "failed",
    "cooldown_rejected",
    "validation_rejected",
    "compensated",
)


class RetentionJobRunner:
    """Deletes expired ledger records on a configurable schedule."""

    def __init__(self, interval_seconds: float = 3600.0):
        self.interval_seconds = max(interval_seconds, 60.0)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="retention-runner")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("Retention cleanup loop failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.interval_seconds
                )
            except asyncio.TimeoutError:
                pass

    async def run_once(self) -> dict[str, int]:
        """Execute one retention pass. Returns per-category deletion counts."""
        stats = {
            "resolved_casts": 0,
            "rejected_casts": 0,
            "idempotency_records": 0,
        }
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)

            resolved_days = settings.RETENTION_RESOLVED_CAST_DAYS
            if resolved_days > 0:
                cutoff = now - timedelta(days=resolved_days)
                stats["resolved_casts"] = self._delete(
                    db,
                    db.query(FishingCast).filter(
                        FishingCast.status == "resolved",
                        FishingCast.requested_at < cutoff,
                    ),
                )

            rejected_days = settings.RETENTION_REJECTED_CAST_DAYS
            if rejected_days > 0:
                cutoff = now - timedelta(days=rejected_days)
                stats["rejected_casts"] = self._delete(
                    db,
                    db.query(FishingCast).filter(
                        FishingCast.status.in_(REJECTED_STATUSES),
                        FishingCast.requested_at < cutoff,
                    ),
                )

            idempotency_days = settings.RETENTION_EXPIRED_IDEMPOTENCY_DAYS
            if idempotency_days > 0:
                # Always drop already-expired rows, not just old ones.
                expired_cutoff = now - timedelta(days=idempotency_days)
                stats["idempotency_records"] = self._delete(
                    db,
                    db.query(IdempotencyRecord).filter(
                        IdempotencyRecord.expires_at < now,
                        IdempotencyRecord.created_at < expired_cutoff,
                    ),
                )

            if any(stats.values()):
                logger.info("Retention cleanup: %s", stats)
            return stats
        finally:
            db.close()

    def _delete(self, db, query) -> int:
        deleted = query.delete(synchronize_session=False)
        db.commit()
        return deleted
