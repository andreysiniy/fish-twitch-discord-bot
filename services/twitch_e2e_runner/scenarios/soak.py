from __future__ import annotations

from typing import Any


async def run_soak(ctx: Any, scenario: str) -> dict[str, Any]:
    ready = await ctx.engine.ready()
    return {
        "status": "skipped",
        "checks": {
            "scenario": scenario,
            "engine_ready": True,
            "reason": "Soak execution is an explicit long-running deployment job",
            "engine": ready,
        },
    }
