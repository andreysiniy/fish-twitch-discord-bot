"""Scheduled rebuild of the fishing_stats_daily aggregate table.

Runs on an interval in the worker process and idempotently recomputes the
previous UTC day (and optionally today) so dashboards never aggregate millions
of raw cast rows per request.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from core.config import settings
from infrastructure.database import SessionLocal
from infrastructure.repositories.fishing_cast_query_repo import FishingCastQueryRepository

logger = logging.getLogger(__name__)


class DailyStatsJobRunner:
    def __init__(self, interval_seconds: float = 3600.0):
        self.interval_seconds = max(interval_seconds, 300.0)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="daily-stats-runner")

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
                logger.exception("Daily stats rebuild loop failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.interval_seconds
                )
            except asyncio.TimeoutError:
                pass

    async def run_once(self) -> dict[str, int]:
        """Rebuild yesterday (and today) idempotently; returns buckets written."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        with SessionLocal() as db:
            repo = FishingCastQueryRepository(db)
            buckets = repo.rebuild_daily_stats(yesterday)
            if not settings.FISHING_CAST_LEDGER_ENABLED:
                return {"buckets": buckets}
            buckets += repo.rebuild_daily_stats(now)
            db.commit()
        logger.info("daily_stats_rebuilt", buckets=buckets)
        return {"buckets": buckets}
