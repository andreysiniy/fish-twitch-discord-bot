from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "twitch_e2e_runner"))
runner_config = _load("twitch_e2e_config_test", ROOT / "services/twitch_e2e_runner/config.py")
runner_manager = _load(
    "twitch_e2e_manager_test", ROOT / "services/twitch_e2e_runner/run_manager.py"
)
runner_catalog = _load(
    "twitch_e2e_catalog_test", ROOT / "services/twitch_e2e_runner/scenarios/catalog.py"
)
runner_permissions = _load(
    "twitch_e2e_permissions_test", ROOT / "services/twitch_e2e_runner/assertions/permissions.py"
)
runner_economy = _load(
    "twitch_e2e_economy_test", ROOT / "services/twitch_e2e_runner/assertions/economy.py"
)
runner_scenario_helpers = _load(
    "twitch_e2e_scenario_helpers_test", ROOT / "services/twitch_e2e_runner/scenarios/helpers.py"
)
seed_stub_points = runner_scenario_helpers.seed_stub_points
RunnerSettings = runner_config.RunnerSettings
RunManager = runner_manager.RunManager
redact_result = runner_manager.redact_result


def test_race_catalog_covers_all_r_scenarios_without_unrouted_ids() -> None:
    race_ids = set(runner_catalog.ECONOMY_SCENARIOS + runner_catalog.GAMEPLAY_SCENARIOS)
    groups = (
        runner_catalog.ECONOMY_RACES,
        runner_catalog.INVENTORY_RACES,
        runner_catalog.CROSS_DOMAIN_RACES,
        runner_catalog.FISHING_RACES,
        runner_catalog.WORKER_RACES,
        runner_catalog.RESILIENCE_RACES,
        runner_catalog.PROVIDER_FAULT_RACES,
    )
    assert race_ids <= set().union(*groups)


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


def test_permission_assertion_accepts_backend_access_denied_message() -> None:
    runner_permissions.assert_permission_rejected({"text": "Access denied for this channel"})


def test_successful_buy_assertion_uses_durable_operation_evidence() -> None:
    runner_economy.assert_successful_buy(
        {
            "evidence": [
                {
                    "state": "completed",
                    "points_delta": "-120",
                    "mass_delta": "1.00",
                    "response_payload": {"chat_message": "You bought 1kg of fish."},
                }
            ]
        },
        0,
    )


def test_stub_points_fixture_seeds_every_requested_actor() -> None:
    class Stub:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, str]] = []

        async def set_balance(self, user_id: str, balance: int, channel_id: str) -> None:
            self.calls.append((user_id, balance, channel_id))

    class Pool:
        def require(self, *names: str) -> None:
            assert names == ("viewer1", "viewer2")

    stub = Stub()
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(
            mode="stub",
            channel_id="test-channel",
            provider_channel_id="provider-channel",
            actors=lambda: [
                SimpleNamespace(name="viewer1", user_id="viewer-one-id", login="viewer-one"),
                SimpleNamespace(name="viewer2", user_id="viewer-two-id", login="viewer-two"),
            ],
        ),
        pool=Pool(),
        stub=stub,
    )

    fixture = asyncio.run(seed_stub_points(ctx, ["viewer1", "viewer2"]))

    assert fixture == {
        "points_balance_seeded": 100_000,
        "points_actors": ["viewer1", "viewer2"],
    }
    assert stub.calls == [
        ("viewer-one", 100_000, "provider-channel"),
        ("viewer-two", 100_000, "provider-channel"),
    ]


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
