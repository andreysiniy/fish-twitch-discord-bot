"""Discord-side lightweight metric counters.

The discord_gateway runs without the game engine package on its path, so these
counters are kept local instead of importing ``core.metrics``. The format and
names match the engine counters so any log pipeline can aggregate them.
"""

import threading

_LOCK = threading.Lock()
_COUNTERS: dict[str, int] = {}


def _inc(name: str, labels: dict[str, str] | None = None) -> None:
    key = name
    if labels:
        rendered = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        key = f"{name}{{{rendered}}}"
    with _LOCK:
        _COUNTERS[key] = _COUNTERS.get(key, 0) + 1


def count_wizard_timeout(flow: str) -> None:
    _inc("fishing_wizard_timeouts_total", {"flow": flow})


def set_wizard_sessions_active(value: int) -> None:
    with _LOCK:
        _COUNTERS["fishing_wizard_sessions_active"] = value
