from __future__ import annotations

from typing import Any


def assert_bot_reply(message: Any, expected: str | None = None) -> dict[str, Any]:
    if isinstance(message, dict):
        text = str(message.get("text", ""))
        message_id = str(message.get("message_id", ""))
        author_login = str(message.get("author_login", ""))
    else:
        text = str(getattr(message, "text", ""))
        message_id = str(getattr(message, "message_id", ""))
        author_login = str(getattr(message, "author_login", ""))
    if expected and expected.lower() not in text.lower():
        raise AssertionError(f"Expected bot reply to contain {expected!r}")
    return {
        "message_id": message_id,
        "text": text,
        "author_login": author_login,
    }


def assert_no_secret(value: Any) -> None:
    text = str(value).lower()
    for marker in ("access_token", "refresh_token", "client_secret", "authorization"):
        if marker in text:
            raise AssertionError(f"Secret-shaped field leaked into test result: {marker}")
