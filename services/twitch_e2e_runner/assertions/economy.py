from __future__ import annotations

from typing import Any


def provider_write_count(requests: dict[str, Any]) -> int:
    return sum(1 for item in requests.get("requests", []) if item.get("operation") == "points_write")


def assert_at_most_one_provider_write(requests: dict[str, Any]) -> None:
    count = provider_write_count(requests)
    if count > 1:
        raise AssertionError(f"Expected at most one provider write, got {count}")

