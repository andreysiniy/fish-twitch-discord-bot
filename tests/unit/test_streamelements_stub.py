from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import httpx
import pytest

_spec = spec_from_file_location(
    "streamelements_stub_test", Path(__file__).resolve().parents[2] / "services/streamelements_stub/main.py"
)
assert _spec and _spec.loader
_module = module_from_spec(_spec)
sys.modules["streamelements_stub_test"] = _module
_spec.loader.exec_module(_module)
app = _module.app


@pytest.mark.asyncio
async def test_stub_can_program_ambiguous_write_without_logging_tokens() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://stub") as client:
        await client.post("/internal/test/reset")
        await client.post(
            "/internal/test/balance",
            json={"user_id": "viewer1", "channel_id": "channel", "balance": 100},
        )
        scripted = await client.post(
            "/internal/test/script",
            json={
                "operation": "points_write",
                "steps": [{"action": "apply_write"}, {"action": "drop_connection"}],
            },
        )
        assert scripted.status_code == 200
        response = await client.put("/kappa/v2/points/channel/viewer1/-10")
        assert response.status_code == 502
        state = await client.get("/internal/test/state")
        assert state.json()["balances"]["channel:viewer1"] == 90
        requests = await client.get("/internal/test/requests")
        assert "authorization" not in requests.text.lower()
