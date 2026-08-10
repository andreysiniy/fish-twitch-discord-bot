import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from core.messages import MsgKey, resolve_message
from core.security import decrypt_token
from domain.logic.mass import apply_mass_mutation
from domain.schemas.fishing import FishResponse
from infrastructure.database import SessionLocal
from infrastructure.models import Channel, EconomyOperation, OutboxEvent, UserProgress
from infrastructure.se_client import SEApiClient, SETransientError


logger = logging.getLogger(__name__)


class SEJobRunner:
    MAX_ATTEMPTS = 8
    LEASE_SECONDS = 60
    SAFE_RETRY_ERRORS = (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.PoolTimeout,
        SETransientError,
    )

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
        event_id: str | None = None
        try:
            if self._recover_expired_lease(db):
                return True

            now = datetime.now(timezone.utc)
            event = (
                db.query(OutboxEvent)
                .filter(
                    OutboxEvent.state == "pending",
                    OutboxEvent.next_attempt_at <= now,
                )
                .order_by(OutboxEvent.created_at.asc())
                .with_for_update(skip_locked=True)
                .first()
            )
            if not event:
                return False
            event_id = event.id

            operation = self._operation_for_event(db, event)
            if not operation:
                event.state = "dead_letter"
                event.last_error = "Economy operation not found"
                event.lease_expires_at = None
                db.commit()
                return True

            channel = db.query(Channel).filter(Channel.id == operation.channel_id).first()
            if not channel or not channel.se_token or not channel.se_channel_id:
                self._finalize_failure(
                    db,
                    event,
                    operation,
                    "StreamElements integration not configured",
                )
                db.commit()
                return True

            event.state = "processing"
            event.lease_expires_at = now + timedelta(seconds=self.LEASE_SECONDS)
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
            event.lease_expires_at = None
            operation.state = "completed"
            operation.external_applied = True
            operation.last_error = None
            db.commit()
            return True
        except self.SAFE_RETRY_ERRORS as error:
            db.rollback()
            if event_id:
                self._schedule_retry(db, event_id, error)
            return True
        except (PermissionError, ValueError) as error:
            db.rollback()
            if event_id:
                self._dead_letter(db, event_id, error)
            return True
        except Exception as error:
            db.rollback()
            if event_id:
                self._mark_reconciliation(db, event_id, error)
                return True
            raise
        finally:
            db.close()

    def _schedule_retry(self, db, event_id: str, error: Exception) -> None:
        event = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.id == event_id)
            .with_for_update()
            .first()
        )
        if not event:
            return
        event.attempts += 1
        event.last_error = type(error).__name__
        event.lease_expires_at = None
        operation = self._operation_for_event(db, event, for_update=True)
        if operation:
            operation.attempts = event.attempts
            operation.last_error = event.last_error
        if event.attempts >= self.MAX_ATTEMPTS:
            self._finalize_failure(db, event, operation, event.last_error)
        else:
            event.state = "pending"
            if operation:
                operation.state = "pending"
            delay = min(2**event.attempts, 300)
            event.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        db.commit()

    def _dead_letter(self, db, event_id: str, error: Exception) -> None:
        event = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.id == event_id)
            .with_for_update()
            .first()
        )
        if not event:
            return
        operation = self._operation_for_event(db, event, for_update=True)
        self._finalize_failure(db, event, operation, type(error).__name__)
        db.commit()

    def _finalize_failure(
        self,
        db,
        event: OutboxEvent,
        operation: EconomyOperation | None,
        error: str,
    ) -> None:
        event.state = "dead_letter"
        event.last_error = error
        event.lease_expires_at = None
        if not operation:
            return
        operation.last_error = error
        if operation.operation_type != "sell":
            operation.state = "failed"
            return
        if operation.compensated_at is not None:
            operation.state = "compensated"
            return

        user = (
            db.query(UserProgress)
            .filter(UserProgress.id == operation.user_id)
            .with_for_update()
            .first()
        )
        channel = db.query(Channel).filter(Channel.id == operation.channel_id).first()
        if not user or not channel:
            event.state = "reconciliation_required"
            operation.state = "reconciliation_required"
            operation.last_error = "Sell refund target not found"
            return

        refund = max(-Decimal(str(operation.mass_delta)), Decimal("0"))
        apply_mass_mutation(user, refund, track_total=False)
        operation.compensated_at = datetime.now(timezone.utc)
        operation.external_applied = False
        operation.state = "compensated"
        operation.response_payload = FishResponse(
            chat_message=resolve_message(channel.config or {}, MsgKey.SELL_MASS_FAILED),
            xp_gained=0,
            actions=[],
        ).model_dump(mode="json")

    def _recover_expired_lease(self, db) -> bool:
        now = datetime.now(timezone.utc)
        event = (
            db.query(OutboxEvent)
            .filter(
                OutboxEvent.state == "processing",
                (OutboxEvent.lease_expires_at.is_(None))
                | (OutboxEvent.lease_expires_at <= now),
            )
            .order_by(OutboxEvent.created_at.asc())
            .with_for_update(skip_locked=True)
            .first()
        )
        if not event:
            return False
        self._set_reconciliation(
            db,
            event,
            "Worker lease expired during external request",
        )
        db.commit()
        return True

    def _mark_reconciliation(self, db, event_id: str, error: Exception) -> None:
        event = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.id == event_id)
            .with_for_update()
            .first()
        )
        if not event:
            return
        self._set_reconciliation(db, event, type(error).__name__)
        db.commit()

    def _set_reconciliation(self, db, event: OutboxEvent, error: str) -> None:
        event.state = "reconciliation_required"
        event.last_error = error
        event.lease_expires_at = None
        operation = self._operation_for_event(db, event, for_update=True)
        if operation:
            operation.state = "reconciliation_required"
            operation.last_error = error

    def _mark_ambiguous_jobs_for_reconciliation(self) -> None:
        db = SessionLocal()
        try:
            while self._recover_expired_lease(db):
                pass
        finally:
            db.close()

    def _operation_for_event(
        self,
        db,
        event: OutboxEvent,
        *,
        for_update: bool = False,
    ) -> EconomyOperation | None:
        operation_id = str((event.payload or {}).get("operation_id") or "")
        query = db.query(EconomyOperation).filter(EconomyOperation.id == operation_id)
        if for_update:
            query = query.with_for_update()
        return query.first()
