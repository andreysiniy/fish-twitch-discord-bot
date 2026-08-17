from __future__ import annotations

from typing import Any


def assert_correlation(evidence: dict[str, Any], source_request_id: str) -> None:
    if not evidence.get("available"):
        return
    if evidence.get("source_request_id") != source_request_id:
        raise AssertionError("Engine evidence does not match Twitch source request")

