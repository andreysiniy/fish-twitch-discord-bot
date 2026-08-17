import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.messages import MsgKey, resolve_message
from core.security import decrypt_integration_token
from domain.economy import EconomyDomainError
from domain.logic.mass import apply_mass_mutation
from domain.schemas.fishing import FishResponse
from infrastructure.database import SessionLocal
from infrastructure.models import (
    Channel,
    ChannelIntegration,
    EconomyOperation,
    EconomyOperationEvent,
    EconomyProviderAttempt,
    OutboxEvent,
    UserProgress,
)
from infrastructure.se_client import (
    ProviderAmbiguousWriteError,
    ProviderConnectionNotSentError,
    ProviderError,
    ProviderRateLimitError,
    SEApiClient,
)
from integrations.streamelements.constants import (
    STREAMELEMENTS_POINTS_MAX,
    provider_headroom,
    validate_credit,
    validate_debit,
    validate_provider_balance,
)
from services.economy_reconciliation import apply_confirmed_buy_mass

logger = logging.getLogger(__name__)


class SEJobRunner:
    MAX_ATTEMPTS = 8
    LEASE_SECONDS = 60
    SAFE_RETRY_ERRORS = (ProviderConnectionNotSentError, ProviderRateLimitError)

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
        await self.se_client.close()

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
            integration_query = db.query(ChannelIntegration).filter(
                ChannelIntegration.channel_id == operation.channel_id,
                ChannelIntegration.provider == "streamelements",
                ChannelIntegration.status.in_(("connected", "degraded")),
            )
            if operation.integration_id is not None:
                integration_query = integration_query.filter(
                    ChannelIntegration.id == operation.integration_id
                )
            integration = integration_query.first()
            if not channel or not integration:
                self._finalize_failure(
                    db,
                    event,
                    operation,
                    "StreamElements integration not configured",
                )
                db.commit()
                return True

            # A reconnect/rebind may replace the provider channel while an
            # older outbox operation is waiting. Never debit or credit the
            # replacement identity: the operation snapshot is its tenant
            # boundary and must be reconciled instead.
            if (
                operation.provider_channel_id_snapshot
                and operation.provider_channel_id_snapshot
                != integration.provider_channel_id
            ):
                self._set_reconciliation(
                    db,
                    event,
                    "STREAM_ELEMENTS_PROVIDER_IDENTITY_MISMATCH",
                )
                db.commit()
                return True

            event.state = "processing"
            event.lease_expires_at = now + timedelta(seconds=self.LEASE_SECONDS)
            operation.state = "processing"
            db.commit()

            try:
                token = decrypt_integration_token(
                    integration.credential_ciphertext,
                    key_version=integration.credential_key_version,
                )
            except ValueError:
                integration.status = "invalid"
                integration.last_check_at = datetime.now(timezone.utc)
                integration.last_error_at = integration.last_check_at
                integration.last_error_code = "STREAM_ELEMENTS_CREDENTIAL_DECRYPTION_FAILED"
                integration.consecutive_failures += 1
                integration.next_validation_at = integration.last_check_at + timedelta(hours=6)
                db.commit()
                self._finalize_failure(db, event, operation, integration.last_error_code)
                db.commit()
                return True
            provider_balance = validate_provider_balance(
                await self.se_client.get_balance(
                    str(integration.provider_channel_id), token, operation.twitch_username
                )
            )
            operation.provider_balance_before = provider_balance
            operation.provider_points_cap = STREAMELEMENTS_POINTS_MAX
            operation.provider_points_headroom_before = provider_headroom(provider_balance)
            if operation.points_delta >= 0:
                validate_credit(provider_balance, operation.points_delta)
            else:
                validate_debit(provider_balance, -operation.points_delta)
            request_started_at = datetime.now(timezone.utc)
            attempt = EconomyProviderAttempt(
                operation_id=operation.id,
                attempt_no=operation.attempts + 1,
                request_kind="add_points",
                points_delta=operation.points_delta,
                provider_balance_before=provider_balance,
                provider_points_cap=STREAMELEMENTS_POINTS_MAX,
                request_started_at=request_started_at,
                outcome="started",
            )
            db.add(attempt)
            operation.attempts += 1
            self._append_event(
                db,
                operation,
                "provider_write_started",
                "processing",
                "processing",
            )
            db.flush()
            result = await self.se_client.add_points(
                str(integration.provider_channel_id),
                token,
                operation.twitch_username,
                operation.points_delta,
            )

            event.state = "processed"
            event.processed_at = datetime.now(timezone.utc)
            event.lease_expires_at = None
            operation.state = "external_applied"
            operation.external_applied = True
            operation.external_applied_at = datetime.now(timezone.utc)
            operation.provider_balance_after = result.balance_after
            operation.provider_status_code = result.status_code
            if result.balance_after is not None:
                result_balance = validate_provider_balance(result.balance_after)
                operation.provider_balance_after = result_balance
                operation.provider_points_headroom_after = provider_headroom(result_balance)
            attempt.request_finished_at = datetime.now(timezone.utc)
            attempt.latency_ms = max(
                int((attempt.request_finished_at - request_started_at).total_seconds() * 1000),
                0,
            )
            attempt.http_status = result.status_code
            attempt.provider_balance_after = result.balance_after
            attempt.provider_request_id = result.provider_request_id
            attempt.outcome = "confirmed"
            self._append_event(
                db,
                operation,
                "provider_write_confirmed",
                "processing",
                "external_applied" if operation.operation_type == "buy" else "completed",
            )
            apply_confirmed_buy_mass(db, operation, actor_type="worker")
            operation.state = "completed"
            operation.completed_at = datetime.now(timezone.utc)
            operation.last_error = None
            db.commit()
            return True
        except self.SAFE_RETRY_ERRORS as error:
            db.rollback()
            if event_id:
                self._schedule_retry(db, event_id, error)
            return True
        except ProviderAmbiguousWriteError as error:
            db.rollback()
            if event_id:
                self._mark_reconciliation(db, event_id, error)
                return True
            raise
        except (ProviderError, EconomyDomainError) as error:
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
        event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).with_for_update().first()
        if not event:
            return
        event.attempts += 1
        event.last_error = type(error).__name__
        event.lease_expires_at = None
        operation = self._operation_for_event(db, event, for_update=True)
        if operation:
            operation.attempts = event.attempts
            operation.last_error = event.last_error
            self._finish_attempt_error(db, operation, error, "retryable")
        if event.attempts >= self.MAX_ATTEMPTS:
            self._finalize_failure(db, event, operation, event.last_error)
        else:
            event.state = "pending"
            if operation:
                operation.state = "pending"
            delay = min(2**event.attempts, 300)
            event.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        db.commit()

    def _append_event(self, db, operation, event_type, from_state, to_state) -> None:
        sequence = getattr(operation, "_event_sequence", None)
        if sequence is None:
            last = (
                db.query(EconomyOperationEvent.sequence_no)
                .filter(EconomyOperationEvent.operation_id == operation.id)
                .order_by(EconomyOperationEvent.sequence_no.desc())
                .first()
            )
            sequence = last[0] if last else 0
        sequence += 1
        operation._event_sequence = sequence
        db.add(
            EconomyOperationEvent(
                operation_id=operation.id,
                sequence_no=sequence,
                event_type=event_type,
                from_state=from_state,
                to_state=to_state,
                actor_type="worker",
                event_metadata={},
            )
        )

    def _dead_letter(self, db, event_id: str, error: Exception) -> None:
        event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).with_for_update().first()
        if not event:
            return
        operation = self._operation_for_event(db, event, for_update=True)
        if operation:
            self._finish_attempt_error(db, operation, error, "rejected")
        self._finalize_failure(db, event, operation, getattr(error, "code", type(error).__name__))
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

        refund = max(-Decimal(str(operation.mass_delta)), Decimal(0))
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
                (OutboxEvent.lease_expires_at.is_(None)) | (OutboxEvent.lease_expires_at <= now),
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
        event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).with_for_update().first()
        if not event:
            return
        self._set_reconciliation(db, event, getattr(error, "code", type(error).__name__))
        db.commit()

    def _set_reconciliation(self, db, event: OutboxEvent, error: str) -> None:
        event.state = "reconciliation_required"
        event.last_error = error
        event.lease_expires_at = None
        operation = self._operation_for_event(db, event, for_update=True)
        if operation:
            self._finish_attempt_error(db, operation, error, "ambiguous")
            operation.state = "reconciliation_required"
            operation.last_error = error

    def _finish_attempt_error(self, db, operation, error: Exception | str, outcome: str) -> None:
        attempt = (
            db.query(EconomyProviderAttempt)
            .filter(EconomyProviderAttempt.operation_id == operation.id)
            .order_by(EconomyProviderAttempt.attempt_no.desc())
            .first()
        )
        if not attempt or attempt.request_finished_at is not None:
            return
        finished_at = datetime.now(timezone.utc)
        attempt.request_finished_at = finished_at
        attempt.latency_ms = max(
            int((finished_at - attempt.request_started_at).total_seconds() * 1000), 0
        )
        attempt.outcome = outcome
        attempt.error_code = getattr(error, "code", None) or str(error)
        attempt.error_message = type(error).__name__ if isinstance(error, Exception) else None

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
