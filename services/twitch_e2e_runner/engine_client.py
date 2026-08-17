"""Read-only engine and provider control clients used by the runner."""

from __future__ import annotations

from typing import Any

import httpx

try:
    from .config import RunnerSettings
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from config import RunnerSettings


class EngineClient:
    def __init__(self, cfg: RunnerSettings):
        self.cfg = cfg
        self._client = httpx.AsyncClient(base_url=cfg.engine_url.rstrip("/"), timeout=10.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def ready(self) -> dict[str, Any]:
        response = await self._client.get("/health/ready")
        response.raise_for_status()
        return response.json()

    async def get_evidence(self, source_request_id: str) -> dict[str, Any]:
        response = await self._client.get(
            "/internal/e2e/evidence",
            params={"source_request_id": source_request_id},
            headers=self._headers(),
        )
        if response.status_code == 404:
            return {"available": False}
        response.raise_for_status()
        return {"available": True, **response.json()}

    def _headers(self) -> dict[str, str]:
        return {"X-E2E-Service-Key": self.cfg.engine_api_key} if self.cfg.engine_api_key else {}


class StubClient:
    def __init__(self, cfg: RunnerSettings):
        self.cfg = cfg
        self._client = httpx.AsyncClient(base_url=cfg.stub_url.rstrip("/"), timeout=10.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def reset(self) -> dict[str, Any]:
        response = await self._client.post("/internal/test/reset", headers=self._headers())
        response.raise_for_status()
        return response.json()

    async def set_balance(self, user_id: str, balance: int, channel_id: str = "stub-channel") -> dict[str, Any]:
        response = await self._client.post(
            "/internal/test/balance",
            json={"user_id": user_id, "balance": balance, "channel_id": channel_id},
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def script(self, operation: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        response = await self._client.post(
            "/internal/test/script",
            json={"operation": operation, "steps": steps},
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def state(self) -> dict[str, Any]:
        response = await self._client.get("/internal/test/state", headers=self._headers())
        response.raise_for_status()
        return response.json()

    async def requests(self) -> dict[str, Any]:
        response = await self._client.get("/internal/test/requests", headers=self._headers())
        response.raise_for_status()
        return response.json()

    def _headers(self) -> dict[str, str]:
        return {"X-Control-Key": self.cfg.stub_control_key} if self.cfg.stub_control_key else {}
