from __future__ import annotations

from typing import Any


async def run_inventory_race(ctx, scenario: str) -> dict[str, Any]:
    return {"status": "skipped", "checks": {"reason": "Inventory fixture is not enabled", "scenario": scenario}}

