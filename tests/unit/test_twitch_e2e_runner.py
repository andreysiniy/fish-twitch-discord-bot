from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "services/twitch_e2e_runner")

from config import RunnerSettings
from run_manager import RunManager, redact_result


def test_runner_settings_keep_actor_tokens_out_of_summary(monkeypatch) -> None:
    monkeypatch.setenv("TWITCH_E2E_OWNER_USER_ID", "owner-id")
    monkeypatch.setenv("TWITCH_E2E_OWNER_LOGIN", "owner")
    monkeypatch.setenv("TWITCH_E2E_OWNER_ACCESS_TOKEN", "access-secret")
    settings = RunnerSettings()
    actor = settings.actors()[0]
    assert actor.configured
    assert "access-secret" not in str(actor.safe_summary())


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

