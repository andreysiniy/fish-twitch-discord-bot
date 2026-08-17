from __future__ import annotations

from typing import Any


async def run_channel_membership(ctx: Any, scenario: str) -> dict[str, Any]:
    """Keep membership scenarios explicit until the gateway test adapter exists."""

    ready = await ctx.engine.ready()
    return {
        "status": "skipped",
        "checks": {
            "scenario": scenario,
            "engine_ready": True,
            "reason": "Twitch membership fault adapter is deployment-owned",
            "engine": ready,
        },
    }
