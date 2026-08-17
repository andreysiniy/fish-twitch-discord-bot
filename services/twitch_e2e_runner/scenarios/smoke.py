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
    if ctx.cfg.mode == "stub":
        checks["transport"] = "stub"
        return {"status": "passed", "checks": checks}
    ctx.pool.require("viewer1")
    replies = await ctx.pool.send_concurrent(
        [("viewer1", "!fishstats"), ("viewer1", "!fishrate")]
    )
    checks["replies"] = [assert_bot_reply(reply) for reply in replies]
    return {"status": "passed", "checks": checks}
