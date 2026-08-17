from __future__ import annotations

from typing import Any


async def run_provider_fault(ctx, scenario: str) -> dict[str, Any]:
    if ctx.cfg.mode != "stub":
        return {"status": "skipped", "checks": {"reason": "Provider fault scenarios require the deterministic stub"}}
    await ctx.stub.reset()
    await ctx.stub.set_balance("viewer1", 100_000)
    await ctx.stub.script("points_write", [{"action": "apply_write"}, {"action": "drop_connection"}])
    return {
        "status": "ready",
        "checks": {"scenario": scenario, "fault_scripted": True, "automatic_retry": False},
    }

