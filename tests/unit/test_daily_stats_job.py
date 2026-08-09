import asyncio
import logging
from types import SimpleNamespace

from services.retention.daily_stats_job_runner import DailyStatsJobRunner


class _FakeRepo:
    def __init__(self):
        self.calls = 0

    def rebuild_daily_stats(self, day):
        self.calls += 1
        return 1


class _FakeDb:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def commit(self):
        pass


def test_run_once_logs_snapshot_without_raising(caplog) -> None:
    runner = DailyStatsJobRunner(interval_seconds=3600.0)
    repo = _FakeRepo()
    runner.run_once.__globals__["SessionLocal"] = lambda: _FakeDb()
    runner.run_once.__globals__["FishingCastQueryRepository"] = lambda db: repo
    runner.run_once.__globals__["settings"] = SimpleNamespace(FISHING_CAST_LEDGER_ENABLED=True)
    with caplog.at_level(logging.INFO):
        result = asyncio.run(runner.run_once())
    assert result == {"buckets": 2}
    assert repo.calls == 2
    assert "daily_stats_rebuilt buckets=2" in caplog.text
