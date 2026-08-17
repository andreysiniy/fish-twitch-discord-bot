from __future__ import annotations

from typing import Any

try:
    from .helpers import execute_commands, transport_unavailable
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from scenarios.helpers import execute_commands, transport_unavailable


INVENTORY_COMMANDS: dict[str, list[tuple[str, str]]] = {
    "R42": [("viewer1", "!fish"), ("viewer1", "!fishtrash 1")],
    "R43": [("viewer1", "!fishequip 1"), ("viewer1", "!fishequip 1")],
    "R44": [("viewer1", "!fishequip 1"), ("viewer1", "!fishtrash 1")],
    "R99": [("viewer1", "!fish"), ("viewer2", "!fish")],
    "R104": [("viewer1", "!fishtrash 1"), ("viewer1", "!fishtrash 1")],
    "R105": [("viewer1", "!fishtrash 1"), ("viewer1", "!fish"), ("viewer1", "!fishtrash 1")],
    "R106": [("viewer1", "!fishequip 1"), ("viewer1", "!fishequip 1")],
    "R107": [("viewer1", "!fishequip 1"), ("viewer1", "!fishequip 2")],
    "R108": [("viewer1", "!fishequip 1"), ("viewer1", "!fishtrash 1")],
}


async def run_inventory_race(ctx, scenario: str) -> dict[str, Any]:
    commands = INVENTORY_COMMANDS.get(scenario)
    if not commands:
        return {
            "status": "skipped",
            "checks": {"reason": "No inventory command recipe", "scenario": scenario},
        }
    skipped = transport_unavailable(ctx, scenario)
    if skipped:
        return skipped
    checks = await execute_commands(ctx, scenario, commands)
    return {"status": "passed", "checks": checks}

