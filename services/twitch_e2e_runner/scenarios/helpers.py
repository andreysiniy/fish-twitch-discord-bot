"""Small helpers shared by real-transport E2E scenarios."""

from __future__ import annotations

from typing import Any

try:
    from ..assertions.common import assert_bot_reply
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from assertions.common import assert_bot_reply


def transport_unavailable(ctx: Any, scenario: str) -> dict[str, Any] | None:
    if ctx.cfg.transport_enabled:
        return None
    return {
        "status": "skipped",
        "checks": {
            "scenario": scenario,
            "reason": "Real Twitch transport is disabled; no production command was sent",
        },
    }


async def execute_commands(
    ctx: Any,
    scenario: str,
    commands: list[tuple[str, str]],
) -> dict[str, Any]:
    actors = sorted({actor for actor, _ in commands})
    ctx.pool.require(*actors)
    replies = await ctx.pool.send_concurrent(commands)
    checks: dict[str, Any] = {
        "scenario": scenario,
        "commands": [command for _, command in commands],
        "replies": [assert_bot_reply(reply) for reply in replies],
    }
    evidence = []
    for reply in replies:
        source_request_id = getattr(reply, "source_request_id", "")
        if source_request_id:
            evidence.append(
                await ctx.engine.wait_for_evidence(
                    source_request_id,
                    timeout_seconds=ctx.cfg.command_timeout_seconds,
                )
            )
    if evidence:
        checks["evidence"] = evidence
        missing = [item for item in evidence if not item.get("available")]
        if missing:
            raise AssertionError("A production Twitch command has no durable engine evidence")
    return checks
