"""HTTP entry point for real Twitch E2E and race suites."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

try:
    from .config import COMMAND_SURFACE, settings
    from .engine_client import EngineClient, StubClient
    from .run_manager import RunManager, redact_result
    from .scenarios.boundary import run_boundary
    from .scenarios.catalog import (
        ALL_SCENARIOS,
        BOUNDARY_SCENARIOS,
        CHANNEL_SCENARIOS,
        CROSS_DOMAIN_RACES,
        ECONOMY_RACES,
        FISHING_RACES,
        HEALTH_SCENARIOS,
        INVENTORY_RACES,
        PROVIDER_FAULT_RACES,
        RESILIENCE_RACES,
        SOAK_SCENARIOS,
        WORKER_RACES,
    )
    from .scenarios.channels import run_channel_membership
    from .scenarios.cross_domain_races import run_cross_domain_race
    from .scenarios.economy_races import run_economy_race
    from .scenarios.fishing import run_fishing_race
    from .scenarios.health import run_health
    from .scenarios.inventory import run_inventory_race
    from .scenarios.permissions import run_permissions
    from .scenarios.provider_faults import run_provider_fault
    from .scenarios.resilience import run_resilience
    from .scenarios.smoke import run_smoke
    from .scenarios.soak import run_soak
    from .scenarios.worker_races import run_worker_race
    from .twitch_client import ActorPool
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from config import COMMAND_SURFACE, settings
    from engine_client import EngineClient, StubClient
    from run_manager import RunManager, redact_result
    from scenarios.boundary import run_boundary
    from scenarios.catalog import (
        ALL_SCENARIOS,
        BOUNDARY_SCENARIOS,
        CHANNEL_SCENARIOS,
        CROSS_DOMAIN_RACES,
        ECONOMY_RACES,
        FISHING_RACES,
        HEALTH_SCENARIOS,
        INVENTORY_RACES,
        PROVIDER_FAULT_RACES,
        RESILIENCE_RACES,
        SOAK_SCENARIOS,
        WORKER_RACES,
    )
    from scenarios.channels import run_channel_membership
    from scenarios.cross_domain_races import run_cross_domain_race
    from scenarios.economy_races import run_economy_race
    from scenarios.fishing import run_fishing_race
    from scenarios.health import run_health
    from scenarios.inventory import run_inventory_race
    from scenarios.permissions import run_permissions
    from scenarios.provider_faults import run_provider_fault
    from scenarios.resilience import run_resilience
    from scenarios.smoke import run_smoke
    from scenarios.soak import run_soak
    from scenarios.worker_races import run_worker_race
    from twitch_client import ActorPool

logger = logging.getLogger(__name__)
_CHANNEL_STATE_MUTATING_SCENARIOS = {"permissions", "R48", "R116", "R117"}


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(default="viewer1", min_length=1, max_length=40)
    secondary_actor: str | None = Field(default=None, min_length=1, max_length=40)


@dataclass
class ScenarioContext:
    cfg: Any
    pool: ActorPool
    engine: EngineClient
    stub: StubClient
    command_names: tuple[str, ...]


app = FastAPI(title="Twitch E2E Runner", version="1.0.0")
manager = RunManager(
    settings.result_db_path,
    deployment_version=settings.deployment_version,
    git_sha=settings.git_sha,
)
pool = ActorPool(settings)
engine = EngineClient(settings)
stub = StubClient(settings)


def require_runner_key(x_e2e_key: str | None = Header(default=None)) -> None:
    if settings.runner_api_key and x_e2e_key != settings.runner_api_key:
        raise HTTPException(status_code=403, detail="Invalid E2E runner key")
    if not settings.enabled:
        raise HTTPException(status_code=503, detail="Twitch E2E runner is disabled")


@app.on_event("shutdown")
async def shutdown() -> None:
    await pool.stop()
    await engine.close()
    await stub.close()


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "healthy", "service": "twitch_e2e_runner"}


@app.get("/health/ready")
async def health_ready() -> dict[str, Any]:
    if not settings.enabled:
        raise HTTPException(status_code=503, detail="Twitch E2E runner is disabled")
    result: dict[str, Any] = {
        "status": "ready",
        "service": "twitch_e2e_runner",
        "mode": settings.mode,
        "transport": settings.transport,
        "configured_actors": pool.configured_names,
    }
    try:
        result["engine"] = await engine.ready()
    except Exception as error:
        raise HTTPException(status_code=503, detail="Game engine is not ready") from error
    return result


def _context() -> ScenarioContext:
    return ScenarioContext(
        cfg=settings,
        pool=pool,
        engine=engine,
        stub=stub,
        command_names=tuple(spec.name for spec in COMMAND_SURFACE),
    )


async def _run_scenario(scenario: str) -> dict[str, Any]:
    if scenario == "smoke":
        return await run_smoke(_context())
    if scenario == "permissions":
        return await run_permissions(_context())
    context = _context()
    if scenario in PROVIDER_FAULT_RACES:
        return await run_provider_fault(context, scenario)
    if scenario in WORKER_RACES:
        return await run_worker_race(context, scenario)
    if scenario in RESILIENCE_RACES:
        return await run_resilience(context, scenario)
    if scenario in ECONOMY_RACES:
        return await run_economy_race(_context(), scenario)
    if scenario in INVENTORY_RACES:
        return await run_inventory_race(context, scenario)
    if scenario in CROSS_DOMAIN_RACES:
        return await run_cross_domain_race(context, scenario)
    if scenario in FISHING_RACES:
        return await run_fishing_race(context, scenario)
    if scenario in HEALTH_SCENARIOS:
        return await run_health(context, scenario)
    if scenario in CHANNEL_SCENARIOS:
        return await run_channel_membership(context, scenario)
    if scenario in BOUNDARY_SCENARIOS:
        return await run_boundary(context, scenario)
    if scenario in SOAK_SCENARIOS:
        return await run_soak(context, scenario)
    return {
        "status": "skipped",
        "checks": {
            "reason": "Scenario fixture is not enabled in this deployment",
            "scenario": scenario,
        },
    }


async def _restore_channel_state(context: ScenarioContext) -> dict[str, Any]:
    """Restore shared Twitch fixtures after a stateful scenario or before a suite.

    The race suite intentionally exercises destructive owner operations.  The
    commands are sent through the production bot so this reset validates the
    same authorization and command path as the scenarios, while preventing a
    failed/interrupted run from leaking a closed market or stale access role
    into the next scenario.
    """

    replies: list[str] = []
    try:
        context.pool.require("owner")
        for command in (
            "!fishmoddel viewer1",
            "!fishmodadd editor editor",
            "!fisheconomy on",
            "!fisheconomy buy on",
            "!fisheconomy sell on",
        ):
            reply = await context.pool.send_and_wait("owner", command)
            replies.append(reply.text)
    except Exception as error:  # noqa: BLE001 - cleanup must be reported to the suite
        logger.exception("Economy state cleanup failed")
        return {
            "status": "failed",
            "error": type(error).__name__,
            "message": "Could not restore shared Twitch channel state",
            "replies": replies,
        }
    return {"status": "passed", "replies": replies}


async def _run_scenario_isolated(scenario: str) -> dict[str, Any]:
    if scenario not in _CHANNEL_STATE_MUTATING_SCENARIOS:
        return await _run_scenario(scenario)

    result: dict[str, Any] | None = None
    scenario_error: Exception | None = None
    try:
        result = await _run_scenario(scenario)
    except Exception as error:  # noqa: BLE001 - cleanup must run after failed scenarios
        scenario_error = error

    cleanup = await _restore_channel_state(_context())
    if scenario_error is not None:
        if cleanup["status"] == "failed":
            logger.error("Shared Twitch channel state was not restored after a failed scenario")
        raise scenario_error

    assert result is not None
    checks = result.setdefault("checks", {})
    if isinstance(checks, dict):
        checks["channel_state_cleanup"] = cleanup
    if cleanup["status"] == "failed":
        result["status"] = "failed"
        result["error"] = {
            "stage": "cleanup",
            "code": "CHANNEL_STATE_NOT_RESTORED",
            "message": cleanup["message"],
        }
    return result


@app.post("/internal/e2e/run/{scenario}", dependencies=[Depends(require_runner_key)])
async def run_one(scenario: str, request: RunRequest | None = None) -> dict[str, Any]:
    scenario = scenario.strip()
    if scenario not in ALL_SCENARIOS:
        raise HTTPException(status_code=404, detail="Unknown E2E scenario")
    actor = request.actor if request else "viewer1"
    secondary_actor = request.secondary_actor if request else None
    run_id = await manager.start(
        "manual", scenario, settings.channel, actor, secondary_actor
    )
    try:
        result = redact_result(await _run_scenario_isolated(scenario))
    except Exception as error:
        logger.exception("E2E scenario failed scenario=%s run_id=%s", scenario, run_id)
        result = {
            "status": "failed",
            "error": {"stage": "scenario", "code": type(error).__name__, "message": str(error)},
            "checks": {},
        }
    await manager.finish(run_id, result)
    return {"run_id": run_id, "scenario": scenario, **result}


@app.post("/internal/e2e/run-suite/{suite}", dependencies=[Depends(require_runner_key)])
async def run_suite(suite: str, request: RunRequest | None = None) -> dict[str, Any]:
    suites = {
        "smoke": ("smoke",),
        "permissions": ("permissions",),
        "economy_race": ("R01", "R02", "R03", "R08", "R13", "R35"),
        "economy_faults": ("R09", "R12", "R27", "R30", "R61", "R71"),
        "cross_domain": ("R93", "R96", "R104", "R105", "R109"),
        "resilience": ("R32", "R53", "R82", "C05", "C10"),
        "nightly": ALL_SCENARIOS,
    }
    scenarios = suites.get(suite)
    if scenarios is None:
        raise HTTPException(status_code=404, detail="Unknown E2E suite")
    actor = request.actor if request else "viewer1"
    setup = await _restore_channel_state(_context())
    if setup["status"] == "failed":
        return {
            "suite": suite,
            "status": "failed",
            "setup": setup,
            "results": [],
        }
    results = []
    for scenario in scenarios:
        secondary_actor = request.secondary_actor if request else None
        run_id = await manager.start(suite, scenario, settings.channel, actor, secondary_actor)
        try:
            result = redact_result(await _run_scenario_isolated(scenario))
        except Exception as error:  # noqa: BLE001 - persist a safe scenario failure
            result = {
                "status": "failed",
                "error": {"stage": "scenario", "code": type(error).__name__, "message": str(error)},
                "checks": {},
            }
        await manager.finish(run_id, result)
        results.append({"run_id": run_id, "scenario": scenario, **result})
    return {"suite": suite, "setup": setup, "results": results}


@app.get("/internal/e2e/runs/{run_id}", dependencies=[Depends(require_runner_key)])
async def get_run(run_id: str) -> dict[str, Any]:
    result = await manager.get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="E2E run not found")
    return redact_result(result)
