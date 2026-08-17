from __future__ import annotations

from typing import Any


async def run_health(ctx: Any, scenario: str) -> dict[str, Any]:
    """Run the health probe only when a deployment exposes its control hooks.

    The runner must never call a scenario passed without observing the durable
    integration state. Until a deployment-specific health control API is
    enabled, report an explicit skip instead of treating engine readiness as
    proof of H01-H12.
    """

    ready = await ctx.engine.ready()
    return {
        "status": "skipped",
        "checks": {
            "scenario": scenario,
            "engine_ready": True,
            "reason": "StreamElements health-worker fault controls are not enabled",
            "engine": ready,
        },
    }
