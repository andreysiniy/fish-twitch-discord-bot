import asyncio
import logging
from datetime import datetime, timedelta, timezone

from core.security import decrypt_token
from infrastructure.database import SessionLocal
from infrastructure.models import Channel, EconomyOperation, OutboxEvent
from infrastructure.se_client import SEApiClient


logger = logging.getLogger(__name__)


class SEJobRunner:
    MAX_ATTEMPTS = 8

    def __init__(self, poll_interval_seconds: float = 1.0):
        self.poll_interval_seconds = max(poll_interval_seconds, 0.2)
        self.se_client = SEApiClient()
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._mark_ambiguous_jobs_for_reconciliation()
        self._task = asyncio.create_task(self._run_loop(), name="se-outbox-runner")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                processed = await self._run_once()
            except Exception:
                logger.exception("StreamElements outbox loop failed")
                processed = False
            if not processed:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass

    async def _run_once(self) -> bool:
        db = SessionLocal()
        event: OutboxEvent | None = None
        try:
            event = (
                db.query(OutboxEvent)
                .filter(
                    OutboxEvent.state == "pending",
                    OutboxEvent.next_attempt_at <= datetime.now(timezone.utc),
                )
                .order_by(OutboxEvent.created_at.asc())
                .with_for_update(skip_locked=True)
                .first()
            )
            if not event:
                return False

            operation_id = str((event.payload or {}).get("operation_id") or "")
            operation = db.query(EconomyOperation).filter(EconomyOperation.id == operation_id).first()
            if not operation:
                event.state = "dead_letter"
                event.last_error = "Economy operation not found"
                db.commit()
                return True

            channel = db.query(Channel).filter(Channel.id == operation.channel_id).first()
            if not channel or not channel.se_token or not channel.se_channel_id:
                event.state = "dead_letter"
                event.last_error = "StreamElements integration not configured"
                operation.state = "failed"
                db.commit()
                return True

            event.state = "processing"
            operation.state = "processing"
            db.commit()

            token = decrypt_token(channel.se_token)
            await self.se_client.add_points(
                str(channel.se_channel_id),
                token,
                operation.twitch_username,
                operation.points_delta,
            )

            event.state = "processed"
            event.processed_at = datetime.now(timezone.utc)
            operation.state = "completed"
            operation.external_applied = True
            db.commit()
            return True
        except (PermissionError, ValueError) as error:
            db.rollback()
            if event is not None:
                self._schedule_retry(db, event.id, error)
            return True
        finally:
            db.close()

    def _schedule_retry(self, db, event_id: str, error: Exception) -> None:
        event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
        if not event:
            return
        event.attempts += 1
        event.last_error = type(error).__name__
        if event.attempts >= self.MAX_ATTEMPTS:
            event.state = "dead_letter"
            operation_id = str((event.payload or {}).get("operation_id") or "")
            operation = db.query(EconomyOperation).filter(EconomyOperation.id == operation_id).first()
            if operation:
                operation.state = "failed"
                operation.last_error = event.last_error
        else:
            event.state = "pending"
            delay = min(2 ** event.attempts, 300)
            event.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        db.commit()

    def _mark_ambiguous_jobs_for_reconciliation(self) -> None:
        db = SessionLocal()
        try:
            events = db.query(OutboxEvent).filter(OutboxEvent.state == "processing").all()
            for event in events:
                event.state = "reconciliation_required"
                event.last_error = "Worker stopped during external request"
                operation_id = str((event.payload or {}).get("operation_id") or "")
                operation = db.query(EconomyOperation).filter(EconomyOperation.id == operation_id).first()
                if operation:
                    operation.state = "reconciliation_required"
                    operation.last_error = event.last_error
            db.commit()
        finally:
            db.close()
