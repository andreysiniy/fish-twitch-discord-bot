from __future__ import annotations

from typing import Any

try:
    from ..assertions.reconciliation import assert_reconciliation_required
    from .helpers import execute_commands, seed_stub_points, transport_unavailable
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from assertions.reconciliation import assert_reconciliation_required
    from scenarios.helpers import execute_commands, seed_stub_points, transport_unavailable


FAULT_COMMANDS: dict[str, tuple[str, str]] = {
    "R09": ("viewer1", "!fishbuy 5"),
    "R10": ("viewer1", "!fishbuy 5"),
    "R11": ("viewer1", "!fishbuy 5"),
    "R12": ("viewer1", "!fishsell 5"),
    "R15": ("viewer1", "!fishbuy 5"),
    "R16": ("viewer1", "!fishsell 5"),
    "R68": ("viewer1", "!fishbuy 5"),
    "R69": ("viewer1", "!fishbuy 5"),
    "R70": ("viewer1", "!fishbuy 5"),
    "R71": ("viewer1", "!fishbuy 5"),
    "R72": ("viewer1", "!fishbuy 5"),
    "R73": ("viewer1", "!fishbuy 5"),
    "R74": ("viewer1", "!fishbuy 5"),
}


async def run_provider_fault(ctx, scenario: str) -> dict[str, Any]:
    command = FAULT_COMMANDS.get(scenario)
    if command is None:
        return {
            "status": "skipped",
            "checks": {"reason": "No provider-fault recipe", "scenario": scenario},
        }
    skipped = transport_unavailable(ctx, scenario)
    if skipped:
        return skipped
    if ctx.cfg.mode != "stub":
        return {
            "status": "skipped",
            "checks": {
                "reason": "Provider fault scenarios require the deterministic stub"
            },
        }
    ctx.pool.require(command[0])
    await ctx.stub.reset()
    await seed_stub_points(ctx, [command[0]])
    if scenario in {"R09", "R10", "R11", "R12", "R69", "R71"}:
        steps = [{"action": "apply_write"}, {"action": "drop_connection"}]
    elif scenario in {"R68"}:
        steps = [{"action": "malformed"}]
    elif scenario in {"R72", "R73", "R74"}:
        steps = [{"action": "status", "status": 429 if scenario in {"R72", "R73"} else 503}]
    else:
        steps = [{"action": "drop_connection"}]
    await ctx.stub.script("points_read" if scenario == "R68" else "points_write", steps)
    # A malformed balance response must not create an EconomyOperation, so a
    # delayed Twitch reply cannot be correlated to durable evidence here.
    # Validate the provider request trace below instead of requiring a ledger
    # row that is intentionally forbidden by this scenario.
    checks = await execute_commands(
        ctx,
        scenario,
        [command],
        require_all_evidence=scenario != "R68",
    )
    checks["fault_scripted"] = steps
    evidence = checks.get("evidence", [])
    if scenario == "R68":
        requests = await ctx.stub.requests()
        checks["provider_requests"] = requests
        operations = [item.get("operation") for item in requests.get("requests", [])]
        if "points_read" not in operations or "points_write" in operations:
            raise AssertionError("Malformed provider balance must not trigger a provider write")
    if scenario in {"R09", "R12", "R69", "R71"} and evidence:
        assert_reconciliation_required(evidence[0])
    return {"status": "passed", "checks": checks}

