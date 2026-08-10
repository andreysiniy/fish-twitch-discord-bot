import asyncio
import inspect
from unittest.mock import MagicMock

from services.retention.retention_job_runner import (
    REJECTED_STATUSES,
    RetentionJobRunner,
)


class _FakeQuery:
    def __init__(self):
        self.deleted = 0

    def filter(self, *args):
        return self

    def delete(self, synchronize_session=False):
        self.deleted += 1
        return 1


class _FakeModel:
    status = MagicMock()
    requested_at = MagicMock()
    expires_at = MagicMock()
    created_at = MagicMock()


class _FakeDb:
    def __init__(self):
        self._commit_count = 0

    def query(self, model):
        return _FakeQuery()

    def commit(self):
        self._commit_count += 1

    def close(self):
        pass


def test_rejected_statuses_family() -> None:
    assert "failed" in REJECTED_STATUSES
    assert "cooldown_rejected" in REJECTED_STATUSES
    assert "validation_rejected" in REJECTED_STATUSES
    assert "resolved" not in REJECTED_STATUSES


def test_outbox_success_states_match_the_persisted_state_machine() -> None:
    source = inspect.getsource(RetentionJobRunner.run_once)
    assert '("processed", "dead_letter", "failed", "compensated")' in source


def test_runner_constructs_with_interval() -> None:
    runner = RetentionJobRunner(interval_seconds=120.0)
    assert runner.interval_seconds == 120.0


def test_run_once_executes_all_passes() -> None:
    runner = RetentionJobRunner(interval_seconds=60.0)
    db = _FakeDb()
    runner.run_once.__globals__["SessionLocal"] = lambda: db
    stats = asyncio.run(runner.run_once())
    assert {
        "resolved_casts",
        "rejected_casts",
        "idempotency_records",
        "admin_audit_log",
        "economy_operations",
        "outbox_events",
        "inventory_item_use_records",
    } <= stats.keys()
