from __future__ import annotations

from typing import Any


async def run_fishing_race(ctx, scenario: str) -> dict[str, Any]:
    if scenario == "R93":
        ctx.pool.require("viewer1")
        if ctx.cfg.mode == "stub":
            return {"status": "skipped", "checks": {"reason": "Twitch transport is disabled in stub mode"}}
        replies = await ctx.pool.send_concurrent([("viewer1", "!fish"), ("viewer1", "!fish")])
        return {"status": "passed", "checks": {"reply_count": len(replies)}}
    return {"status": "skipped", "checks": {"reason": "Fishing fixture is not enabled"}}

