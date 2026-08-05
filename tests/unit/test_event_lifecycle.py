from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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
