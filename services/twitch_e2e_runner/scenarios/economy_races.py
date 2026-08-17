from __future__ import annotations

from typing import Any

try:
    from ..assertions.economy import (
        assert_at_most_one_provider_write,
        assert_successful_buy,
        provider_write_count,
    )
    from .helpers import execute_commands, seed_stub_points, transport_unavailable
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from assertions.economy import (
        assert_at_most_one_provider_write,
        assert_successful_buy,
        provider_write_count,
    )
    from scenarios.helpers import execute_commands, seed_stub_points, transport_unavailable

RACE_COMMANDS: dict[str, list[tuple[str, str]]] = {
    "R01": [("viewer1", "!fishbuy 5"), ("viewer1", "!fishsell 5")],
    "R02": [("viewer1", "!fishbuy 5"), ("viewer1", "!fishbuy 5")],
    "R03": [("viewer1", "!fishsell 5"), ("viewer1", "!fishsell 5")],
    "R04": [("viewer1", "!fishbuy all"), ("viewer1", "!fishbuy all")],
    "R05": [("viewer1", "!fishsell all"), ("viewer1", "!fishsell all")],
    "R08": [("viewer1", "!fishbuy 5"), ("viewer1", "!fishsell 5")],
    "R49": [("viewer1", "!fishbuy 5"), ("viewer2", "!fishbuy 5")],
    "R50": [("viewer1", "!fishsell 5"), ("viewer2", "!fishsell 5")],
    "R91": [("viewer1", "!fishbuy 5"), ("viewer1", "!fishbuy 5")],
    "R93": [("viewer1", "!fish"), ("viewer1", "!fish")],
    "R96": [("viewer1", "!fish"), ("viewer2", "!fish")],
}

_CONCURRENT_PROVIDER_READ_DELAY_SECONDS = 5.0


async def run_economy_race(ctx, scenario: str) -> dict[str, Any]:
    commands = RACE_COMMANDS.get(scenario)
    if not commands:
        return {
            "status": "skipped",
            "checks": {"reason": "Scenario requires a dedicated fault hook"},
        }
    skipped = transport_unavailable(ctx, scenario)
    if skipped:
        return skipped
    actors = sorted({actor for actor, _ in commands})
    ctx.pool.require(*actors)
    if ctx.cfg.mode == "stub":
        await ctx.stub.reset()
        await seed_stub_points(ctx, actors)
        # The Twitch runner deliberately paces IRC messages.  Delay the first
        # provider read so a second command still arrives while the durable
        # per-viewer economy lock is held; otherwise this race test would only
        # exercise two valid sequential purchases.
        if len(actors) == 1 and len(commands) > 1:
            await ctx.stub.script(
                "points_read",
                [{"action": "delay", "seconds": _CONCURRENT_PROVIDER_READ_DELAY_SECONDS}],
            )
    checks = await execute_commands(ctx, scenario, commands, require_all_evidence=False)
    if ctx.cfg.mode == "stub":
        requests = await ctx.stub.requests()
        checks["provider_requests"] = requests
        if len({actor for actor, _ in commands}) == 1:
            assert_at_most_one_provider_write(requests)
        if scenario in {"R02", "R04", "R91"}:
            available = [
                index
                for index, evidence in enumerate(checks.get("evidence", []))
                if evidence.get("available")
            ]
            if len(available) != 1 or provider_write_count(requests) != 1:
                raise AssertionError(
                    f"Expected one successful buy in {scenario}, "
                    f"got evidence={len(available)}, writes={provider_write_count(requests)}"
                )
            assert_successful_buy(checks, available[0])
    return {"status": "passed", "checks": checks}
