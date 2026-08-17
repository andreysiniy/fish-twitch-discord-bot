from __future__ import annotations

from typing import Any

try:
    from ..assertions.economy import assert_successful_buy
    from .helpers import execute_commands, seed_stub_points, transport_unavailable
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from assertions.economy import assert_successful_buy
    from scenarios.helpers import execute_commands, seed_stub_points, transport_unavailable


BOUNDARY_COMMANDS: dict[str, list[tuple[str, str]]] = {
    "E01": [("viewer1", "!fishbuy 5"), ("viewer1", "!fishsell 5")],
    "E02": [("viewer1", "!fishbuy   5KG  ")],
    "E03": [("viewer1", "!fishbuy NaN")],
    "E04": [("viewer1", "!fishbuy 0.005")],
    "E05": [("viewer1", "!fishbuy 1.5")],
    "E06": [("viewer1", "!fishsell 1.5")],
    "E07": [("viewer1", "!fishbuy 2147483648")],
    "E08": [("viewer1", "!fishbuy all")],
    "E09": [("viewer1", "!fishbuy 999999999999999999999999")],
    "E10": [("viewer1", "!fishsell all")],
}
BALANCE_REQUIRED_SCENARIOS = {"E01", "E02", "E05", "E08"}


async def run_boundary(ctx: Any, scenario: str) -> dict[str, Any]:
    commands = BOUNDARY_COMMANDS.get(scenario)
    if not commands:
        return {
            "status": "skipped",
            "checks": {"reason": "No boundary command recipe", "scenario": scenario},
        }
    skipped = transport_unavailable(ctx, scenario)
    if skipped:
        return skipped
    if scenario in BALANCE_REQUIRED_SCENARIOS:
        if ctx.cfg.mode != "stub":
            return {
                "status": "skipped",
                "checks": {
                    "scenario": scenario,
                    "reason": (
                        "Scenario requires a controlled provider balance fixture; use stub mode"
                    ),
                },
            }
        balance_fixture = await seed_stub_points(ctx, ["viewer1"])
    else:
        balance_fixture = None
    checks = await execute_commands(ctx, scenario, commands)
    if balance_fixture:
        checks["points_balance_seeded"] = balance_fixture["points_balance_seeded"]
        checks["points_actors"] = balance_fixture["points_actors"]
    if scenario in BALANCE_REQUIRED_SCENARIOS:
        assert_successful_buy(checks, 0)
    return {"status": "passed", "checks": checks}
