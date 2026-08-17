from __future__ import annotations

from typing import Any

try:
    from ..assertions.common import assert_bot_reply
    from ..assertions.permissions import assert_permission_rejected
    from .helpers import transport_unavailable
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from assertions.common import assert_bot_reply
    from assertions.permissions import assert_permission_rejected
    from scenarios.helpers import transport_unavailable


async def run_permissions(ctx) -> dict[str, Any]:
    skipped = transport_unavailable(ctx, "permissions")
    if skipped:
        return skipped
    ctx.pool.require("owner", "editor", "viewer1")
    replies = await ctx.pool.send_concurrent(
        [("viewer1", "!fisheconomy off"), ("editor", "!fisheconomy off")]
    )
    assert_permission_rejected(replies[0])
    return {
        "status": "passed",
        "checks": {
            "viewer_rejected": assert_bot_reply(replies[0]),
            "editor_reply": assert_bot_reply(replies[1]),
        },
    }
