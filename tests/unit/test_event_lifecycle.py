from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.sql.elements import BinaryExpression

from services.discord_admin_service import DiscordAdminService


def _event(**overrides):
    now = datetime.now(timezone.utc)
    base = {
        "id": 1,
        "event_title": "Lucky",
        "is_active": False,
        "status": "draft",
        "starts_at": None,
        "ends_at": None,
        "activated_at": None,
        "deactivated_at": None,
        "modifier_schema_version": 2,
        "requires_review": False,
        "modifiers": {},
        "override_loot_pool": None,
        "version": 1,
        "updated_at": now,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_event_serialize_includes_durable_lifecycle_fields() -> None:
    service = object.__new__(DiscordAdminService)
    start = datetime(2026, 8, 4, 8, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(seconds=3600)
    event = _event(
        status="active",
        starts_at=start,
        ends_at=end,
        activated_at=start,
        modifier_schema_version=2,
        requires_review=True,
    )
    data = service._serialize_event(event)
    assert data["status"] == "active"
    assert data["starts_at"] == start.isoformat()
    assert data["ends_at"] == end.isoformat()
    assert data["activated_at"] == start.isoformat()
    assert data["modifier_schema_version"] == 2
    assert data["requires_review"] is True


def test_event_serialize_handles_null_timing() -> None:
    service = object.__new__(DiscordAdminService)
    data = service._serialize_event(_event())
    assert data["starts_at"] is None
    assert data["ends_at"] is None
    assert data["deactivated_at"] is None


def test_due_events_are_ended_directly_from_postgres(monkeypatch) -> None:
    """PostgreSQL is authoritative for event deadlines (plan §15)."""
    from datetime import datetime, timedelta, timezone

    from services.eventing.event_lifecycle_service import FishingEventLifecycleService

    now = datetime.now(timezone.utc)
    due = SimpleNamespace(
        id=1,
        channel_id=7,
        is_active=True,
        status="active",
        ends_at=now - timedelta(seconds=30),
        deactivated_at=None,
    )
    future = SimpleNamespace(
        id=2,
        channel_id=8,
        is_active=True,
        status="active",
        ends_at=now + timedelta(hours=1),
        deactivated_at=None,
    )

    class FakeQuery:
        def __init__(self):
            self._now = None

        def filter(self, *args, **kwargs):
            for arg in args:
                if isinstance(arg, BinaryExpression) and hasattr(arg.right, "utcoffset"):
                    self._now = arg.right
            return self

        def with_for_update(self, skip_locked=False):
            return self

        def limit(self, n):
            return self

        def all(self):
            now = self._now or datetime.now(timezone.utc)
            return [e for e in [due, future] if e.ends_at <= now]

    class FakeDb:
        def query(self, model):
            return FakeQuery()

    class FakeChannelRepo:
        def __init__(self):
            self.db = FakeDb()
            self.ended = []
            self.deactivated = []

        def set_active_fishing_event(self, channel_id, value):
            self.deactivated.append(channel_id)

    class FakeScheduler:
        def __init__(self):
            self.cancelled = []
            self.jobs = []

        def get_due_jobs(self, limit=50):
            return []

        def cancel_scheduled_disable(self, channel_twitch_id):
            self.cancelled.append(channel_twitch_id)

    channel_repo = FakeChannelRepo()
    scheduler = FakeScheduler()
    service = FishingEventLifecycleService.__new__(FishingEventLifecycleService)
    service.channel_repo = channel_repo
    service.scheduler = scheduler
    service._mark_event_ended = lambda event: channel_repo.ended.append(event.id)

    ended_count = service._end_due_events_from_postgres(limit=10)
    assert ended_count == 1
    assert channel_repo.deactivated == [7]
    assert channel_repo.ended == [1]


def test_due_event_cancels_scheduler_by_twitch_channel_id() -> None:
    from services.eventing.event_lifecycle_service import FishingEventLifecycleService

    now = datetime.now(timezone.utc)
    due = SimpleNamespace(
        id=1,
        channel_id=7,
        channel=SimpleNamespace(twitch_id="twitch-7"),
        is_active=True,
        status="active",
        ends_at=now - timedelta(seconds=1),
        deactivated_at=None,
    )

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def with_for_update(self, skip_locked=False):
            return self

        def limit(self, amount):
            return self

        def all(self):
            return [due]

    class FakeDb:
        def query(self, model):
            return FakeQuery()

    class FakeChannelRepo:
        db = FakeDb()

        def set_active_fishing_event(self, channel_id, value):
            pass

    class FakeScheduler:
        def __init__(self):
            self.cancelled = []

        def cancel_scheduled_disable(self, value):
            self.cancelled.append(value)

        def get_due_jobs(self, limit=50):
            return []

    scheduler = FakeScheduler()
    service = FishingEventLifecycleService.__new__(FishingEventLifecycleService)
    service.channel_repo = FakeChannelRepo()
    service.scheduler = scheduler
    service._mark_event_ended = lambda event: None

    service._end_due_events_from_postgres()

    assert scheduler.cancelled == ["twitch-7"]
