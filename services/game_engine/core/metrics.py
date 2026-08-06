"""Lightweight in-process metrics counters for the fishing ledger.

The plan's metrics (fishing_casts_total, fishing_duplicate_requests_total, ...)
are recorded here without a Prometheus dependency: increments are cheap, and
``log_summary`` emits them periodically via structured logging so any log
pipeline can scrape them. No secrets or PII are ever attached.
"""

import threading
from collections import defaultdict
from typing import Any

_LOCK = threading.Lock()
_COUNTERS: dict[str, int] = defaultdict(int)
_GAUGES: dict[str, Any] = {}


def inc(name: str, labels: dict[str, str] | None = None) -> None:
    key = name
    if labels:
        rendered = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        key = f"{name}{{{rendered}}}"
    with _LOCK:
        _COUNTERS[key] += 1


def set_gauge(name: str, value: Any, labels: dict[str, str] | None = None) -> None:
    key = name
    if labels:
        rendered = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        key = f"{name}{{{rendered}}}"
    with _LOCK:
        _GAUGES[key] = value


def snapshot() -> dict[str, int | Any]:
    with _LOCK:
        return {**dict(_COUNTERS), **dict(_GAUGES)}


def reset() -> None:
    with _LOCK:
        _COUNTERS.clear()
        _GAUGES.clear()


def log_summary(logger: Any) -> None:
    """Emit the current counter snapshot as one structured log record."""
    values = snapshot()
    if not values:
        return
    logger.info("fishing_metrics_snapshot", metrics=values)


def count_cast(status: str, reward_type: str | None = None) -> None:
    labels = {"status": status}
    if reward_type:
        labels["reward_type"] = reward_type
    inc("fishing_casts_total", labels)


def count_cast_persist_failure() -> None:
    inc("fishing_cast_persist_failures_total")


def count_duplicate_request() -> None:
    inc("fishing_duplicate_requests_total")


def record_cast_duration(seconds: float) -> None:
    set_gauge("fishing_cast_duration_seconds", seconds)


def count_item_drop(item_id: str, status: str) -> None:
    inc("fishing_item_drops_total", {"item_id": item_id, "status": status})


def count_wizard_timeout(flow: str) -> None:
    inc("fishing_wizard_timeouts_total", {"flow": flow})


def set_wizard_sessions_active(value: int) -> None:
    set_gauge("fishing_wizard_sessions_active", value)
