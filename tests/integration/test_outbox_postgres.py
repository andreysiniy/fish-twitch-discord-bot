import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from infrastructure.database import SessionLocal
from infrastructure.models import Channel, EconomyOperation, OutboxEvent, UserProgress
from infrastructure.se_client import SETransientError
from services.eventing.se_job_runner import SEJobRunner


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="requires PostgreSQL",
)


def _sell_operation(db, suffix: str, *, mass: str = "90.00"):
    suffix = f"{suffix}-{uuid.uuid4().hex}"
    channel = Channel(twitch_id=f"outbox-{suffix}", name=f"outbox_{suffix}", config={})
    db.add(channel)
    db.flush()
    user = UserProgress(
        user_twitch_id=f"viewer-{suffix}",
        username=f"viewer_{suffix}",
        channel_id=channel.id,
        current_mass=Decimal(mass),
    )
    db.add(user)
    db.flush()
    operation = EconomyOperation(
        idempotency_key=f"sell-{suffix}",
        operation_type="sell",
        channel_id=channel.id,
        user_id=user.id,
        twitch_username=user.username,
        mass_delta=Decimal("-10.00"),
        points_delta=100,
        state="processing",
        response_payload={},
    )
    db.add(operation)
    db.flush()
    event = OutboxEvent(
        idempotency_key=f"economy:{operation.id}",
        topic="streamelements.points",
        payload={"operation_id": operation.id},
        state="processing",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    db.add(event)
    db.flush()
    return user, operation, event


@pytest.mark.integration
def test_transient_retry_dead_letter_refunds_sell_exactly_once() -> None:
    db = SessionLocal()
    try:
        user, operation, event = _sell_operation(db, "refund")
        runner = SEJobRunner()

        runner._schedule_retry(db, event.id, SETransientError("rate limit"))
        db.refresh(event)
        db.refresh(operation)
        db.refresh(user)
        assert event.state == "pending"
        assert event.attempts == 1
        assert operation.state == "pending"
        assert user.current_mass == Decimal("90.00")

        event.state = "processing"
        event.attempts = runner.MAX_ATTEMPTS - 1
        db.commit()
        runner._schedule_retry(db, event.id, SETransientError("rate limit"))
        db.refresh(event)
        db.refresh(operation)
        db.refresh(user)
        assert event.state == "dead_letter"
        assert operation.state == "compensated"
        assert operation.compensated_at is not None
        assert user.current_mass == Decimal("100.00")
        assert "restored" in operation.response_payload["chat_message"]

        runner._dead_letter(db, event.id, PermissionError("invalid token"))
        db.refresh(user)
        assert user.current_mass == Decimal("100.00")
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_expired_processing_lease_requires_reconciliation_without_refund() -> None:
    db = SessionLocal()
    try:
        user, operation, event = _sell_operation(db, "lease")
        event.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

        assert SEJobRunner()._recover_expired_lease(db) is True
        db.refresh(event)
        db.refresh(operation)
        db.refresh(user)
        assert event.state == "reconciliation_required"
        assert operation.state == "reconciliation_required"
        assert user.current_mass == Decimal("90.00")
    finally:
        db.rollback()
        db.close()
