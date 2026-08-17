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
    from .scenarios.catalog import ALL_SCENARIOS
    from .scenarios.economy_races import run_economy_race
    from .scenarios.permissions import run_permissions
    from .scenarios.smoke import run_smoke
    from .twitch_client import ActorPool
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from config import COMMAND_SURFACE, settings
    from engine_client import EngineClient, StubClient
    from run_manager import RunManager, redact_result
    from scenarios.catalog import ALL_SCENARIOS
    from scenarios.economy_races import run_economy_race
    from scenarios.permissions import run_permissions
    from scenarios.smoke import run_smoke
    from twitch_client import ActorPool

logger = logging.getLogger(__name__)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(default="viewer1", min_length=1, max_length=40)


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
    if scenario.startswith("R"):
        return await run_economy_race(_context(), scenario)
    return {
        "status": "skipped",
        "checks": {"reason": "Scenario fixture is not enabled in this deployment", "scenario": scenario},
    }


@app.post("/internal/e2e/run/{scenario}", dependencies=[Depends(require_runner_key)])
async def run_one(scenario: str, request: RunRequest | None = None) -> dict[str, Any]:
    scenario = scenario.strip()
    if scenario not in ALL_SCENARIOS:
        raise HTTPException(status_code=404, detail="Unknown E2E scenario")
    actor = request.actor if request else "viewer1"
    run_id = await manager.start("manual", scenario, settings.channel, actor)
    try:
        result = redact_result(await _run_scenario(scenario))
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
    results = []
    for scenario in scenarios:
        run_id = await manager.start(suite, scenario, settings.channel, actor)
        try:
            result = redact_result(await _run_scenario(scenario))
        except Exception as error:  # noqa: BLE001 - persist a safe scenario failure
            result = {
                "status": "failed",
                "error": {"stage": "scenario", "code": type(error).__name__, "message": str(error)},
                "checks": {},
            }
        await manager.finish(run_id, result)
        results.append({"run_id": run_id, "scenario": scenario, **result})
    return {"suite": suite, "results": results}


@app.get("/internal/e2e/runs/{run_id}", dependencies=[Depends(require_runner_key)])
async def get_run(run_id: str) -> dict[str, Any]:
    result = await manager.get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="E2E run not found")
    return redact_result(result)
