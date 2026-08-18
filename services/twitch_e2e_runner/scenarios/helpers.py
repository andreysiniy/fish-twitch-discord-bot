"""Small helpers shared by real-transport E2E scenarios."""

from __future__ import annotations

import asyncio
import time
from typing import Any

try:
    from ..assertions.common import assert_bot_reply
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from assertions.common import assert_bot_reply

CONTROLLED_POINTS_BALANCE = 100_000


def stub_provider_channel_id(ctx: Any) -> str:
    """Return the provider channel key used by the configured stub.

    Twitch channel names/IDs and StreamElements provider channel IDs are
    different namespaces.  Stub fixtures must use the same provider ID that
    the game engine integration uses, otherwise a seeded balance is invisible
    to the economy service.
    """

    return ctx.cfg.provider_channel_id or ctx.cfg.channel_id or "stub-channel"


def command_requires_durable_evidence(command: str, reply: dict[str, Any]) -> bool:
    """Return whether a Twitch reply represents a persisted game mutation.

    The evidence API currently covers fishing casts and StreamElements
    operations. Administrative, inventory, travel, validation and cooldown
    replies are valid outcomes but do not create one of those records.
    """

    command_name = command.strip().split(maxsplit=1)[0].lower() if command.strip() else ""
    text = " ".join(str(reply.get("text", "")).lower().split())
    if command_name == "!fish":
        return not any(
            marker in text
            for marker in (
                "cooldown",
                "already processing",
                "temporarily unavailable",
                "could not fish",
                "access denied",
            )
        )
    if command_name in {"!fishbuy", "!fishsell"}:
        # Twitch replies can arrive in a different order from concurrently
        # sent commands.  The command itself is authoritative for the
        # evidence kind; only explicit rejection text should suppress the
        # durable lookup.  This keeps a successful BUY paired with its own
        # source request even when its chat reply was delivered first.
        return not any(
            marker in text
            for marker in (
                "not enough points",
                "net is empty",
                "catch some fish first",
                "currently closed",
                "temporarily unavailable",
                "invalid amount",
                "invalid mass",
                "mass is outside the supported range",
                "mass is too large",
                "usage:",
                "access denied",
                "another fish purchase is already processing",
                "another fish sale is already processing",
                "could not buy",
                "could not sell",
                "economy error",
                "internal server error",
            )
        )
    return False


def expected_evidence_kind(command: str) -> str | None:
    command_name = command.strip().split(maxsplit=1)[0].lower() if command.strip() else ""
    if command_name == "!fish":
        return "cast"
    if command_name in {"!fishbuy", "!fishsell"}:
        return "economy"
    return None


async def seed_stub_points(ctx: Any, actor_names: list[str]) -> dict[str, Any] | None:
    """Seed a deterministic provider balance for scenarios requiring a BUY success."""

    if ctx.cfg.mode != "stub":
        return None
    ctx.pool.require(*actor_names)
    for actor_name in actor_names:
        actor = next(item for item in ctx.cfg.actors() if item.name == actor_name)
        await ctx.stub.set_balance(
            actor.login,
            CONTROLLED_POINTS_BALANCE,
            channel_id=stub_provider_channel_id(ctx),
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


def _source_id_variants(source_request_id: str, command: str) -> list[str]:
    """Return the identifiers that the Twitch gateway may persist.

    TwitchIO does not expose a stable outgoing message id on every transport
    path.  In addition, the fishing command deliberately prefixes Twitch
    message ids with ``twitch-`` while economy operations keep the raw id.
    The runner must validate an id before trusting it instead of assuming the
    echo id is durable evidence.
    """

    source_request_id = str(source_request_id or "")
    if not source_request_id:
        return []
    variants = [source_request_id]
    command_name = command.strip().split(maxsplit=1)[0].lower() if command.strip() else ""
    if command_name == "!fish" and not source_request_id.startswith("twitch-"):
        variants.append(f"twitch-{source_request_id}")
    elif command_name == "!fish" and source_request_id.startswith("twitch-"):
        variants.append(source_request_id.removeprefix("twitch-"))
    return list(dict.fromkeys(variants))


async def resolve_durable_evidence(
    ctx: Any,
    *,
    actor_name: str,
    actor_names: list[str] | None = None,
    command: str,
    source_request_id: str,
    sent_at: float,
    used_source_ids: set[str],
) -> tuple[dict[str, Any], str]:
    """Resolve a Twitch reply to durable evidence without false negatives.

    A Twitch echo id is only a hint: TwitchIO may return an id that differs
    from the id persisted by the gateway, or no id at all.  Probe the hinted
    variants briefly, then use the test-only actor/time index to discover the
    durable id and wait for that record.  The long wait is intentionally used
    only after an actual candidate has been found.
    """

    candidates = _source_id_variants(source_request_id, command)
    probe_timeout = min(2.0, max(0.5, float(ctx.cfg.command_timeout_seconds)))
    for candidate in candidates:
        evidence = await ctx.engine.wait_for_evidence(
            candidate,
            timeout_seconds=probe_timeout,
        )
        if evidence.get("available"):
            used_source_ids.add(candidate)
            return evidence, candidate

    recent_count = 0
    if sent_at and ctx.cfg.channel_id:
        actors_by_name = {actor.name: actor for actor in ctx.cfg.actors()}
        target_actor = actors_by_name.get(actor_name)
        target_login = target_actor.login.lower() if target_actor else ""
        target_user_id = str(target_actor.user_id) if target_actor else ""
        target_kind = expected_evidence_kind(command)
        # A concurrent Twitch response can be delivered through another
        # actor's IRC session.  Search the participating actors rather than
        # trusting response arrival order to identify the sender.
        search_names = actor_names or [actor_name]
        recent_deadline = time.monotonic() + min(
            5.0, max(0.5, float(ctx.cfg.command_timeout_seconds))
        )
        while True:
            recent: list[dict[str, Any]] = []
            for search_name in search_names:
                actor = actors_by_name[search_name]
                recent.extend(
                    await ctx.engine.recent_evidence(
                        channel_id=ctx.cfg.channel_id,
                        twitch_user_id=actor.user_id,
                        login=actor.login,
                        since_epoch=sent_at,
                    )
                )
            recent_count = len(recent)
            recent.sort(key=lambda item: item.get("requested_at") or "")
            for item in recent:
                candidate = str(item.get("source_request_id") or "")
                if not candidate or candidate in used_source_ids:
                    continue
                item_login = str(item.get("login") or "").lower()
                item_user_id = str(item.get("twitch_user_id") or "")
                item_kind = str(item.get("kind") or "")
                if target_kind and item_kind and item_kind != target_kind:
                    continue
                if (item_login or item_user_id) and not (
                    (target_login and item_login == target_login)
                    or (target_user_id and item_user_id == target_user_id)
                ):
                    continue
                evidence = await ctx.engine.wait_for_evidence(
                    candidate,
                    timeout_seconds=ctx.cfg.command_timeout_seconds,
                )
                if evidence.get("available"):
                    used_source_ids.add(candidate)
                    return evidence, candidate
            if time.monotonic() >= recent_deadline:
                break
            await asyncio.sleep(0.25)

    # Preserve the original delayed-evidence behavior as a final fallback.
    # This path is reached only when the test index has not observed the row
    # yet (for example, during a slow database commit).
    if source_request_id:
        evidence = await ctx.engine.wait_for_evidence(
            source_request_id,
            timeout_seconds=ctx.cfg.command_timeout_seconds,
        )
        if evidence.get("available"):
            used_source_ids.add(source_request_id)
            return evidence, source_request_id
        return evidence, source_request_id
    return {
        "available": False,
        "reason": (
            "No durable evidence candidate found "
            f"(recent_items={recent_count}, sent_at={sent_at:.3f})"
        ),
    }, ""


async def execute_commands(
    ctx: Any,
    scenario: str,
    commands: list[tuple[str, str]],
    *,
    require_all_evidence: bool = True,
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
    for index, reply in enumerate(replies):
        if not command_requires_durable_evidence(commands[index][1], checks["replies"][index]):
            evidence.append(
                {
                    "available": False,
                    "reason": "No durable evidence expected for this command outcome",
                }
            )
            continue
        source_request_id = getattr(reply, "source_request_id", "")
        evidence_item, resolved_source_id = await resolve_durable_evidence(
            ctx,
            actor_name=commands[index][0],
            actor_names=actors,
            command=commands[index][1],
            source_request_id=source_request_id,
            sent_at=float(getattr(reply, "sent_at", 0) or 0),
            used_source_ids=used_source_ids,
        )
        if resolved_source_id:
            checks["replies"][index]["source_request_id"] = resolved_source_id
        evidence.append(evidence_item)
    if evidence:
        checks["evidence"] = evidence
        required = [
            index
            for index, (command, reply) in enumerate(zip(commands, checks["replies"]))
            if command_requires_durable_evidence(command[1], reply)
        ]
        missing = [index for index in required if not evidence[index].get("available")]
        if missing and require_all_evidence:
            missing_details = []
            for index in missing:
                item = evidence[index]
                if item.get("available"):
                    continue
                reply = checks["replies"][index]
                reply_text = " ".join(str(reply.get("text", "")).split())
                if len(reply_text) > 180:
                    reply_text = f"{reply_text[:177]}..."
                missing_details.append(
                    f"command {index + 1} {commands[index][1]!r}: "
                    f"echo={reply.get('source_request_id') or '<none>'}, "
                    f"reply={reply_text!r}, "
                    f"reason={item.get('reason') or 'record not found'}"
                )
            raise AssertionError(
                "A production Twitch command has no durable engine evidence: "
                + "; ".join(missing_details)
            )
    return checks
