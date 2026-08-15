"""Small in-process counters for bot gateway operational metrics."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any

_LOCK = Lock()
_COUNTERS: dict[str, int] = defaultdict(int)
_GAUGES: dict[str, Any] = {}


def inc(name: str) -> None:
    with _LOCK:
        _COUNTERS[name] += 1


def set_gauge(name: str, value: Any) -> None:
    with _LOCK:
        _GAUGES[name] = value


def snapshot() -> dict[str, Any]:
    with _LOCK:
        return {**_COUNTERS, **_GAUGES}
