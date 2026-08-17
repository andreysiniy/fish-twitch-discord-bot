from __future__ import annotations

from typing import Any

try:
    from .helpers import execute_commands, seed_stub_points, transport_unavailable
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from scenarios.helpers import execute_commands, seed_stub_points, transport_unavailable


FISHING_COMMANDS: dict[str, list[tuple[str, str]]] = {
    "R93": [("viewer1", "!fish"), ("viewer1", "!fish")],
    "R95": [("viewer1", "!fish"), ("viewer1", "!fish")],
    "R96": [("viewer1", "!fish"), ("viewer2", "!fish")],
    "R97": [("viewer1", "!fish"), ("viewer1", "!fish")],
    "R98": [("viewer1", "!fish"), ("viewer2", "!fish")],
    "R100": [("viewer1", "!fish"), ("viewer2", "!fish")],
    "R101": [("viewer1", "!fish"), ("viewer2", "!fishsell all")],
    "R102": [("viewer1", "!fish"), ("viewer2", "!fishbuy 1")],
    "R103": [("viewer1", "!fish"), ("viewer1", "!fish")],
    "R109": [("viewer1", "!fishtravel 1"), ("viewer1", "!fishtravel 2")],
    "R110": [("viewer1", "!fishtravel 1"), ("viewer1", "!fish")],
}


async def _prepare_fixture(ctx: Any, scenario: str) -> dict[str, Any] | None:
    if scenario == "R102":
        if ctx.cfg.mode != "stub":
            return {
                "skip": True,
                "reason": "R102 requires a controlled provider balance fixture; use stub mode",
            }
        balance_fixture = await seed_stub_points(ctx, ["viewer2"])
        return {
            "points_balance_seeded": balance_fixture["points_balance_seeded"],
            "points_actor": "viewer2",
        }

    if scenario not in {"R100", "R103"} or ctx.cfg.mode != "stub":
        return None
    actor = next(item for item in ctx.cfg.actors() if item.name == "viewer1")
    return await ctx.engine.set_next_cast_fixture(
        channel_id=ctx.cfg.channel_id or ctx.cfg.channel,
        viewer_id=actor.user_id,
        outcome="robbery",
        rng={"robbery_roll": 0.0},
    )


async def run_fishing_race(ctx, scenario: str) -> dict[str, Any]:
    commands = FISHING_COMMANDS.get(scenario)
    if not commands:
        return {
            "status": "skipped",
            "checks": {"reason": "No fishing command recipe", "scenario": scenario},
        }
    skipped = transport_unavailable(ctx, scenario)
    if skipped:
        return skipped
    fixture = await _prepare_fixture(ctx, scenario)
    if fixture and fixture.get("skip"):
        return {"status": "skipped", "checks": {"scenario": scenario, **fixture}}
    checks = await execute_commands(ctx, scenario, commands)
    if fixture:
        if fixture.get("fixture_id"):
            checks["fixture_id"] = fixture["fixture_id"]
        if fixture.get("points_balance_seeded"):
            checks["points_balance_seeded"] = fixture["points_balance_seeded"]
            checks["points_actor"] = fixture["points_actor"]
    if scenario == "R102":
        buy_text = checks["replies"][1]["text"].lower()
        if "bought" not in buy_text:
            raise AssertionError("R102 requires a successful !fishbuy command")
    return {"status": "passed", "checks": checks}

