"""Small helpers shared by real-transport E2E scenarios."""

from __future__ import annotations

from typing import Any

try:
    from ..assertions.common import assert_bot_reply
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from assertions.common import assert_bot_reply

CONTROLLED_POINTS_BALANCE = 100_000


async def seed_stub_points(ctx: Any, actor_names: list[str]) -> dict[str, Any] | None:
    """Seed a deterministic provider balance for scenarios requiring a BUY success."""

    if ctx.cfg.mode != "stub":
        return None
    ctx.pool.require(*actor_names)
    for actor_name in actor_names:
        actor = next(item for item in ctx.cfg.actors() if item.name == actor_name)
        await ctx.stub.set_balance(
            actor.user_id,
            CONTROLLED_POINTS_BALANCE,
            channel_id=(
                ctx.cfg.provider_channel_id
                or ctx.cfg.channel_id
                or "stub-channel"
            ),
        )
    return {
        "points_balance_seeded": CONTROLLED_POINTS_BALANCE,
        "points_actors": actor_names,
    }


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
    used_source_ids: set[str] = set()
    actors_by_name = {actor.name: actor for actor in ctx.cfg.actors()}
    for index, reply in enumerate(replies):
        source_request_id = getattr(reply, "source_request_id", "")
        if not source_request_id and getattr(reply, "sent_at", 0) and ctx.cfg.channel_id:
            actor_name = commands[index][0]
            actor = actors_by_name[actor_name]
            recent = await ctx.engine.recent_evidence(
                channel_id=ctx.cfg.channel_id,
                twitch_user_id=actor.user_id,
                login=actor.login,
                since_epoch=reply.sent_at,
            )
            candidate = next(
                (
                    item.get("source_request_id")
                    for item in recent
                    if item.get("source_request_id")
                    and item["source_request_id"] not in used_source_ids
                ),
                "",
            )
            source_request_id = str(candidate or "")
            if source_request_id:
                used_source_ids.add(source_request_id)
                checks["replies"][index]["source_request_id"] = source_request_id
        if source_request_id:
            evidence.append(
                await ctx.engine.wait_for_evidence(
                    source_request_id,
                    timeout_seconds=ctx.cfg.command_timeout_seconds,
                )
            )
        else:
            evidence.append({"available": False, "reason": "Twitch message ID unavailable"})
    if evidence:
        checks["evidence"] = evidence
        missing = [item for item in evidence if not item.get("available")]
        if missing:
            raise AssertionError("A production Twitch command has no durable engine evidence")
    return checks
