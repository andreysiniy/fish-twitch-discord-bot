from __future__ import annotations

from typing import Any

try:
    from ..assertions.common import assert_bot_reply
    from ..assertions.economy import assert_at_most_one_provider_write
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from assertions.common import assert_bot_reply
    from assertions.economy import assert_at_most_one_provider_write

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


async def run_economy_race(ctx, scenario: str) -> dict[str, Any]:
    commands = RACE_COMMANDS.get(scenario)
    if not commands:
        return {"status": "skipped", "checks": {"reason": "Scenario requires a dedicated fault hook"}}
    actors = sorted({actor for actor, _ in commands})
    ctx.pool.require(*actors)
    if ctx.cfg.mode == "stub":
        await ctx.stub.reset()
        for actor in actors:
            await ctx.stub.set_balance(actor, 100_000)
    replies = await ctx.pool.send_concurrent(commands) if ctx.cfg.mode == "real" else []
    checks: dict[str, Any] = {
        "commands": [command for _, command in commands],
        "replies": [assert_bot_reply(reply) for reply in replies],
    }
    if ctx.cfg.mode == "stub":
        requests = await ctx.stub.requests()
        checks["provider_requests"] = requests
        assert_at_most_one_provider_write(requests)
    return {"status": "passed", "checks": checks}
