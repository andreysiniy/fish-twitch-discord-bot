from __future__ import annotations

from typing import Any


async def run_cross_domain_race(ctx, scenario: str) -> dict[str, Any]:
    return {"status": "skipped", "checks": {"reason": "Cross-domain fixture is not enabled", "scenario": scenario}}

