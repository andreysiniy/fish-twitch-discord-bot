from types import SimpleNamespace

from services.economy_service import EconomyService


class _Query:
    def __init__(self, event):
        self.event = event

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.event


class _Session:
    def __init__(self, event):
        self.event = event

    def query(self, model):
        return _Query(self.event)


def test_processing_outbox_event_gets_a_recovery_lease() -> None:
    event = SimpleNamespace(state="pending", lease_expires_at=None, next_attempt_at=None)
    service = EconomyService.__new__(EconomyService)
    service.db = _Session(event)

    service._mark_outbox(SimpleNamespace(id="operation"), "processing")

    assert event.state == "processing"
    assert event.lease_expires_at is not None


def test_retry_returns_outbox_event_to_pending() -> None:
    event = SimpleNamespace(state="processing", lease_expires_at=object(), next_attempt_at=None)
    service = EconomyService.__new__(EconomyService)
    service.db = _Session(event)

    service._mark_outbox(SimpleNamespace(id="operation"), "pending")

    assert event.state == "pending"
    assert event.lease_expires_at is None
    assert event.next_attempt_at is not None
