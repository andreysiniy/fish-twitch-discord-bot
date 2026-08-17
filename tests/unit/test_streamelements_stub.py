from __future__ import annotations

import sys

import httpx
import pytest


sys.path.insert(0, "services/streamelements_stub")

from main import app  # noqa: E402


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

