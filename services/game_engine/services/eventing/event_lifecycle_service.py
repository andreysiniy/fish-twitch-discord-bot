import logging
from datetime import datetime, timezone

from core import metrics as metrics_module

from infrastructure.models import FishingEvent
from infrastructure.redis_client import RedisClient
from services.eventing.event_scheduler import FishingEventScheduler


class FishingEventLifecycleService:
    def __init__(self, channel_repo):
        self.channel_repo = channel_repo
        self.scheduler = FishingEventScheduler(redis_client=RedisClient.get_client())

    def schedule_auto_disable(
        self,
        channel_twitch_id: str,
        channel_id: int,
        event_id: int,
        event_title: str,
        delay_seconds: int,
        requested_by: str,
    ) -> dict:
        return self.scheduler.schedule_disable(
            channel_twitch_id=channel_twitch_id,
            channel_id=channel_id,
            event_id=event_id,
            event_title=event_title,
            delay_seconds=delay_seconds,
            requested_by=requested_by,
        )

    def cancel_auto_disable(self, channel_twitch_id: str) -> None:
        self.scheduler.cancel_scheduled_disable(channel_twitch_id)

    def apply_due_jobs(self, limit: int = 50) -> None:
        """End due fishing events.

        PostgreSQL is authoritative: every active event whose durable
        ``ends_at`` has passed is ended with FOR UPDATE SKIP LOCKED. The Redis
        schedule is only a fallback/reconciliation path, never the sole source
        of the deadline (plan §15).
        """
        self._end_due_events_from_postgres(limit=limit)
        self._apply_redis_schedule(limit=limit)

    def _end_due_events_from_postgres(self, limit: int = 50) -> int:
        now = datetime.now(timezone.utc)
        due = (
            self.channel_repo.db.query(FishingEvent)
            .filter(
                FishingEvent.is_active.is_(True),
                FishingEvent.ends_at.isnot(None),
                FishingEvent.ends_at <= now,
            )
            .with_for_update(skip_locked=True)
            .limit(limit)
            .all()
        )
        for event in due:
            self.channel_repo.set_active_fishing_event(event.channel_id, None)
            self._mark_event_ended(event)
            self.scheduler.cancel_scheduled_disable(str(event.channel_id))
            metrics_module.inc("fishing_events_auto_disabled_total", {"source": "postgres"})
        return len(due)

    def _apply_redis_schedule(self, limit: int = 50) -> None:
        due_jobs = self.scheduler.get_due_jobs(limit=limit)
        for job in due_jobs:
            if str(job.get("kind", "")).strip().lower() != "disable_fishing_event":
                continue

            job_id = str(job.get("job_id", "")).strip()
            channel_twitch_id = str(job.get("channel_twitch_id", "")).strip()
            if not job_id or not channel_twitch_id:
                continue

            try:
                channel_id = int(job.get("channel_id"))
            except (TypeError, ValueError):
                self.scheduler.complete_job(channel_twitch_id, job_id)
                continue

            event_id = None
            try:
                event_id_raw = job.get("event_id")
                if event_id_raw is not None:
                    event_id = int(event_id_raw)
            except (TypeError, ValueError):
                event_id = None

            active_event = self.channel_repo.get_active_fishing_event(channel_id)
            if active_event and (event_id is None or active_event.id == event_id):
                self.channel_repo.set_active_fishing_event(channel_id, None)
                self._mark_event_ended(active_event)

            self.scheduler.complete_job(channel_twitch_id, job_id)

    def _mark_event_ended(self, event: FishingEvent) -> None:
        """Persist the end time durably; Redis only schedules the transition."""
        now = datetime.now(timezone.utc)
        try:
            event.is_active = False
            event.status = "ended"
            event.deactivated_at = now
            event.ends_at = now
            self.channel_repo.db.flush()
        except Exception as error:  # pragma: no cover - defensive
            logging.getLogger("eventing.lifecycle").warning(
                "Failed to persist event end time", exc_info=error
            )
