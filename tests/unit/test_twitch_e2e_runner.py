from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[2]
runner_config = _load("twitch_e2e_config_test", ROOT / "services/twitch_e2e_runner/config.py")
runner_manager = _load("twitch_e2e_manager_test", ROOT / "services/twitch_e2e_runner/run_manager.py")
RunnerSettings = runner_config.RunnerSettings
RunManager = runner_manager.RunManager
redact_result = runner_manager.redact_result


def test_runner_settings_keep_actor_tokens_out_of_summary(monkeypatch) -> None:
    monkeypatch.setenv("TWITCH_E2E_OWNER_USER_ID", "owner-id")
    monkeypatch.setenv("TWITCH_E2E_OWNER_LOGIN", "owner")
    monkeypatch.setenv("TWITCH_E2E_OWNER_ACCESS_TOKEN", "access-secret")
    settings = RunnerSettings()
    actor = settings.actors()[0]
    assert actor.configured
    assert "access-secret" not in str(actor.safe_summary())


def test_runner_transport_is_explicitly_configured(monkeypatch) -> None:
    monkeypatch.setenv("TWITCH_E2E_TRANSPORT", "real")
    assert RunnerSettings().transport_enabled is True


def test_run_manager_persists_redacted_result(tmp_path) -> None:
    async def scenario() -> None:
        manager = RunManager(str(tmp_path / "runs.sqlite3"))
        run_id = await manager.start("smoke", "smoke", "test-channel", "viewer1")
        result = redact_result(
            {"status": "passed", "checks": {"authorization": "secret", "ok": True}}
        )
        await manager.finish(run_id, result)
        stored = await manager.get(run_id)
        assert stored is not None
        assert stored["status"] == "passed"
        assert stored["checks"]["authorization"] == "[REDACTED]"

    asyncio.run(scenario())


def test_run_manager_persists_secondary_actor(tmp_path) -> None:
    async def scenario() -> None:
        manager = RunManager(str(tmp_path / "runs.sqlite3"))
        run_id = await manager.start(
            "race",
            "R01",
            "test-channel",
            "viewer1",
            "viewer2",
        )
        stored = await manager.get(run_id)
        assert stored is not None
        assert stored["secondary_actor_id"] == "viewer2"

    asyncio.run(scenario())
