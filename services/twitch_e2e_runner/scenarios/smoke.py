from __future__ import annotations

from typing import Any

try:
    from ..assertions.common import assert_bot_reply
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from assertions.common import assert_bot_reply


async def run_smoke(ctx) -> dict[str, Any]:
    checks: dict[str, Any] = {"command_surface": list(ctx.command_names)}
    await ctx.engine.ready()
    checks["engine_ready"] = True
    if not ctx.cfg.transport_enabled:
        checks["transport"] = "disabled"
        return {"status": "passed", "checks": checks}
    ctx.pool.require("viewer1")
    # Keep the smoke path deterministic: Twitch chat may drop back-to-back
    # messages from one actor while the production bot is still replying.
    replies = [
        await ctx.pool.send_and_wait("viewer1", "!fishstats"),
        await ctx.pool.send_and_wait("viewer1", "!fishrate"),
    ]
    checks["replies"] = [
        assert_bot_reply(replies[0]),
        assert_bot_reply(replies[1], "Fish rate"),
    ]
    checks["evidence"] = [
        await ctx.engine.get_evidence(reply.source_request_id)
        for reply in replies
        if reply.source_request_id
    ]
    return {"status": "passed", "checks": checks}
