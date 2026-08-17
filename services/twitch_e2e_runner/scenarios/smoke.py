from __future__ import annotations

from typing import Any

try:
    from ..assertions.common import assert_bot_reply
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from assertions.common import assert_bot_reply


async def run_smoke(ctx) -> dict[str, Any]:
    checks: dict[str, Any] = {"command_surface": list(ctx.command_names)}
    await ctx.engine.ready()
    checks["engine_ready"] = True
    if not ctx.cfg.transport_enabled:
        checks["transport"] = "disabled"
        return {"status": "passed", "checks": checks}
    ctx.pool.require("viewer1")
    # Keep the smoke path deterministic: Twitch chat may drop back-to-back
    # messages from one actor while the production bot is still replying.
    replies = [
        await ctx.pool.send_and_wait("viewer1", "!fishstats"),
        await ctx.pool.send_and_wait("viewer1", "!fishrate"),
    ]
    checks["replies"] = [
        assert_bot_reply(replies[0]),
        assert_bot_reply(replies[1], "Fish rate"),
    ]
    actor = next(item for item in ctx.cfg.actors() if item.name == "viewer1")
    evidence = []
    used_source_ids: set[str] = set()
    for index, reply in enumerate(replies):
        source_request_id = reply.source_request_id
        if not source_request_id and reply.sent_at and ctx.cfg.channel_id:
            recent = await ctx.engine.recent_evidence(
                channel_id=ctx.cfg.channel_id,
                twitch_user_id=actor.user_id,
                login=actor.login,
                since_epoch=reply.sent_at,
            )
            source_request_id = next(
                (
                    item["source_request_id"]
                    for item in recent
                    if item.get("source_request_id")
                    and item["source_request_id"] not in used_source_ids
                ),
                "",
            )
            if source_request_id:
                used_source_ids.add(source_request_id)
                checks["replies"][index]["source_request_id"] = source_request_id
        evidence.append(
            await ctx.engine.wait_for_evidence(
                source_request_id,
                timeout_seconds=ctx.cfg.command_timeout_seconds,
            )
            if source_request_id
            else {"available": False, "reason": "Twitch message ID unavailable"}
        )
    checks["evidence"] = evidence
    return {"status": "passed", "checks": checks}
