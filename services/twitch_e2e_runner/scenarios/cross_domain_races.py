from __future__ import annotations

from typing import Any

try:
    from ..assertions.economy import assert_successful_buy
    from .helpers import execute_commands, seed_stub_points, transport_unavailable
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from assertions.economy import assert_successful_buy
    from scenarios.helpers import execute_commands, seed_stub_points, transport_unavailable


CROSS_DOMAIN_COMMANDS: dict[str, list[tuple[str, str]]] = {
    "R38": [("viewer1", "!fish"), ("viewer1", "!fishsell all")],
    "R39": [("viewer1", "!fish"), ("viewer1", "!fishbuy 1")],
    "R40": [("viewer1", "!fish"), ("viewer1", "!fishtravel 1")],
    "R41": [("viewer1", "!fish"), ("viewer1", "!fishequip 1")],
    "R45": [("owner", "!fishevent 1"), ("viewer1", "!fish")],
    "R46": [("owner", "!fishevent 1"), ("owner", "!fishevent 1")],
    "R47": [("owner", "!fishcd set 10"), ("viewer1", "!fish")],
    "R48": [("owner", "!fisheconomy off"), ("viewer1", "!fishbuy 1")],
    "R111": [("owner", "!fishevent 1"), ("owner", "!fishevent 1")],
    "R112": [("owner", "!fishevent 1"), ("owner", "!fishevent 1 60")],
    "R113": [("owner", "!fishevent 1"), ("viewer1", "!fish")],
    "R114": [("owner", "!fishcd set 0"), ("viewer1", "!fish"), ("viewer1", "!fish")],
    "R115": [("owner", "!fishcd set 10"), ("viewer1", "!fish")],
    "R116": [("owner", "!fishmodadd viewer1 moderator"), ("owner", "!fishmoddel viewer1")],
    "R117": [("owner", "!fishmoddel editor"), ("editor", "!fisheconomy off")],
}


async def run_cross_domain_race(ctx, scenario: str) -> dict[str, Any]:
    commands = CROSS_DOMAIN_COMMANDS.get(scenario)
    if not commands:
        return {
            "status": "skipped",
            "checks": {"reason": "No cross-domain command recipe", "scenario": scenario},
        }
    skipped = transport_unavailable(ctx, scenario)
    if skipped:
        return skipped
    if scenario == "R39":
        if ctx.cfg.mode != "stub":
            return {
                "status": "skipped",
                "checks": {
                    "scenario": scenario,
                    "reason": "R39 requires a controlled provider balance fixture; use stub mode",
                },
            }
        balance_fixture = await seed_stub_points(ctx, ["viewer1"])
    else:
        balance_fixture = None
    checks = await execute_commands(ctx, scenario, commands)
    if balance_fixture:
        checks["points_balance_seeded"] = balance_fixture["points_balance_seeded"]
        checks["points_actors"] = balance_fixture["points_actors"]
    if scenario == "R39":
        assert_successful_buy(checks, 1)
    return {"status": "passed", "checks": checks}

