from __future__ import annotations

from typing import Any

try:
    from .helpers import execute_commands, transport_unavailable
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from scenarios.helpers import execute_commands, transport_unavailable


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
    checks = await execute_commands(ctx, scenario, commands)
    return {"status": "passed", "checks": checks}
