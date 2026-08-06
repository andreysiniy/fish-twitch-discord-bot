"""Admin event toggling: durable ends_at must not kill indefinite activations."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from infrastructure.database import SessionLocal
from infrastructure.models import Channel, FishingEvent
from infrastructure.repositories.channel_repo import ChannelRepository
from services.admin_service import AdminService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="requires PostgreSQL",
)


@pytest.mark.integration
def test_indefinite_event_activation_clears_stale_ends_at() -> None:
    """Activating without a duration must not be killed by the reconciler.

    Regression: a previous timed activation leaves ends_at in the past; the
    durable reconciler treats ends_at as the deadline and instantly ended a
    re-activated indefinite event, so its modifiers never showed in fishstats.
    """
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        channel = Channel(
            twitch_id=f"evt-toggle-{suffix}",
            name="Event Toggle",
            config={},
        )
        db.add(channel)
        db.flush()
        event = FishingEvent(
            channel_id=channel.id,
            event_title="Luck Boost",
            is_active=False,
            modifiers={
                "schema_version": 2,
                "fish_luck_change_percent": "40.00",
            },
        )
        db.add(event)
        db.flush()

        repo = ChannelRepository(db)
        service = AdminService(repo, user_repo=None, config_repo=None)

        # Simulate a previously timed activation that already expired:
        # ends_at is in the past, exactly the poisoned state from the bug.
        event.ends_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.flush()

        # Activate indefinitely (no duration).
        result = service.toggle_fishing_event(
            channel.twitch_id, channel.twitch_id, event.id
        )
        assert result.status == "activated"
        db.refresh(event)
        assert event.is_active is True
        assert event.ends_at is None

        # The durable reconciler must not end the indefinite event.
        service.event_lifecycle.apply_due_jobs(limit=10)
        db.refresh(event)
        assert event.is_active is True

        # Toggle off, then a timed activation sets a durable future deadline.
        result = service.toggle_fishing_event(
            channel.twitch_id, channel.twitch_id, event.id
        )
        assert result.status == "deactivated"
        result = service.toggle_fishing_event(
            channel.twitch_id, channel.twitch_id, event.id, duration_seconds=300
        )
        assert result.status == "activated"
        db.refresh(event)
        assert event.ends_at is not None
        assert event.ends_at > datetime.now(timezone.utc)
    finally:
        db.rollback()
        db.close()
