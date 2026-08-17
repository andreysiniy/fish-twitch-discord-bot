from __future__ import annotations

from typing import Any


def assert_permission_rejected(reply: Any) -> None:
    text = str(reply.get("text", "") if isinstance(reply, dict) else getattr(reply, "text", ""))
    markers = ("permission", "not allowed", "forbidden", "owner")
    if not any(marker in text.lower() for marker in markers):
        raise AssertionError("Expected a permission error from the production bot")
