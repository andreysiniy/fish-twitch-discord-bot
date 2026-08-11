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
    logger.info("fishing_metrics_snapshot metrics=%s", values)


def prometheus_text() -> str:
    """Render the in-process metrics as a scrapeable Prometheus payload."""
    with _LOCK:
        counters = dict(_COUNTERS)
        gauges = dict(_GAUGES)

    lines: list[str] = []
    seen_types: set[str] = set()
    for key, value in {**counters, **gauges}.items():
        name, separator, raw_labels = key.partition("{")
        metric_type = "gauge" if key in gauges else "counter"
        if name not in seen_types:
            lines.append(f"# TYPE {name} {metric_type}")
            seen_types.add(name)
        labels = ""
        if separator and raw_labels.endswith("}"):
            pairs = []
            for pair in raw_labels[:-1].split(","):
                label_name, _, label_value = pair.partition("=")
                escaped = label_value.replace("\\", "\\\\").replace('"', '\\"')
                pairs.append(f'{label_name}="{escaped}"')
            labels = "{" + ",".join(pairs) + "}"
        try:
            rendered = str(float(value)) if isinstance(value, float) else str(value)
        except Exception:
            continue
        lines.append(f"{name}{labels} {rendered}")
    return "\n".join(lines) + ("\n" if lines else "")


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


def count_economy_provider_cap_rejection(operation: str) -> None:
    inc("economy_provider_cap_rejections_total", {"operation": operation})


def count_economy_reconciliation(reason: str) -> None:
    inc("economy_reconciliation_required_total", {"reason": reason})
