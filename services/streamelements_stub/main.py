"""Deterministic StreamElements-compatible provider for race tests.

The stub deliberately keeps credentials out of state and request logs. Faults
are programmed through a private control API and consumed once per matching
provider operation.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

CONTROL_KEY = os.getenv("STREAMELEMENTS_STUB_CONTROL_KEY", "")
MAX_POINTS = 2_147_483_647


class BalanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=120)
    balance: int = Field(ge=0, le=MAX_POINTS)
    channel_id: str = Field(default="stub-channel", min_length=1, max_length=120)


class ScriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str = Field(min_length=1, max_length=80)
    steps: list[dict[str, Any]] = Field(default_factory=list, max_length=32)


class StubState:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.balances: dict[tuple[str, str], int] = {}
        self.scripts: dict[str, list[dict[str, Any]]] = {}
        self.requests: list[dict[str, Any]] = []
        self.provider_channel_id = "stub-channel"

    async def reset(self) -> None:
        async with self.lock:
            self.balances.clear()
            self.scripts.clear()
            self.requests.clear()

    async def record(self, operation: str, method: str, path: str) -> None:
        async with self.lock:
            self.requests.append(
                {
                    "id": str(uuid.uuid4()),
                    "operation": operation,
                    "method": method,
                    "path": path,
                    "at": time.time(),
                }
            )

    async def next_script(self, operation: str) -> list[dict[str, Any]]:
        async with self.lock:
            return list(self.scripts.pop(operation, []))

    async def balance(self, channel_id: str, user_id: str) -> int:
        async with self.lock:
            return self.balances.get((channel_id, user_id), 0)

    async def set_balance(self, channel_id: str, user_id: str, value: int) -> None:
        async with self.lock:
            self.balances[(channel_id, user_id)] = value

    async def adjust(self, channel_id: str, user_id: str, amount: int) -> int:
        async with self.lock:
            before = self.balances.get((channel_id, user_id), 0)
            after = before + amount
            if after < 0 or after > MAX_POINTS:
                raise HTTPException(status_code=400, detail="points balance out of range")
            self.balances[(channel_id, user_id)] = after
            return after


state = StubState()
app = FastAPI(title="StreamElements Test Stub", version="1.0.0")


def require_control(key: str | None) -> None:
    if CONTROL_KEY and key != CONTROL_KEY:
        raise HTTPException(status_code=403, detail="Invalid stub control key")


async def apply_steps(
    operation: str,
    steps: list[dict[str, Any]],
    *,
    channel_id: str | None = None,
    user_id: str | None = None,
    amount: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for step in steps:
        action = str(step.get("action", "")).strip().lower()
        if action in {"delay", "sleep"}:
            await asyncio.sleep(max(float(step.get("seconds", 0)), 0.0))
        elif action in {"status", "http_status"}:
            result["status"] = int(step.get("status", 500))
        elif action in {"malformed", "malformed_json"}:
            result["malformed"] = True
        elif action in {"drop_connection", "connection_reset", "timeout_after_write"}:
            result["drop"] = True
        elif action == "apply_write" and channel_id and user_id and amount is not None:
            result["balance_after"] = await state.adjust(channel_id, user_id, amount)
            result["applied"] = True
        elif action == "external_mutation" and channel_id and user_id:
            result["external_balance"] = await state.adjust(
                channel_id, user_id, int(step.get("amount", 0))
            )
    if result.get("drop"):
        raise HTTPException(status_code=502, detail="Simulated provider connection loss")
    return result


async def scripted_response(
    operation: str,
    *,
    channel_id: str | None = None,
    user_id: str | None = None,
    amount: int | None = None,
) -> dict[str, Any]:
    steps = await state.next_script(operation)
    return await apply_steps(
        operation,
        steps,
        channel_id=channel_id,
        user_id=user_id,
        amount=amount,
    )


@app.get("/health/live")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "streamelements_stub"}


@app.get("/kappa/v2/channels/me")
async def channel_me() -> dict[str, str]:
    await state.record("channel_read", "GET", "/kappa/v2/channels/me")
    result = await scripted_response("channel_read")
    status = result.get("status")
    if status:
        raise HTTPException(status_code=status, detail="scripted channel response")
    return {"_id": state.provider_channel_id}


@app.get("/kappa/v2/points/{channel_id}/{user_id}")
async def get_points(channel_id: str, user_id: str) -> dict[str, Any]:
    await state.record("points_read", "GET", f"/kappa/v2/points/{channel_id}/{user_id}")
    result = await scripted_response("points_read", channel_id=channel_id, user_id=user_id)
    status = result.get("status")
    if status:
        raise HTTPException(status_code=status, detail="scripted balance response")
    if result.get("malformed"):
        return {"points": "NaN"}  # type: ignore[return-value]
    return {"points": await state.balance(channel_id, user_id)}


@app.put("/kappa/v2/points/{channel_id}/{user_id}/{amount}")
async def put_points(channel_id: str, user_id: str, amount: int) -> dict[str, Any]:
    await state.record("points_write", "PUT", f"/kappa/v2/points/{channel_id}/{user_id}/{amount}")
    result = await scripted_response(
        "points_write", channel_id=channel_id, user_id=user_id, amount=amount
    )
    status = result.get("status")
    if status:
        raise HTTPException(status_code=status, detail="scripted points response")
    if not result.get("applied"):
        result["balance_after"] = await state.adjust(channel_id, user_id, amount)
    if result.get("malformed"):
        return {"unexpected": True}
    return {
        "points": result["balance_after"],
        "requestId": str(uuid.uuid4()),
    }


@app.post("/internal/test/reset")
async def reset(x_control_key: str | None = Header(default=None)) -> dict[str, str]:
    require_control(x_control_key)
    await state.reset()
    return {"status": "reset"}


@app.post("/internal/test/balance")
async def set_balance(
    payload: BalanceRequest,
    x_control_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_control(x_control_key)
    await state.set_balance(payload.channel_id, payload.user_id, payload.balance)
    return {"channel_id": payload.channel_id, "user_id": payload.user_id, "balance": payload.balance}


@app.post("/internal/test/script")
async def set_script(
    payload: ScriptRequest,
    x_control_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_control(x_control_key)
    async with state.lock:
        state.scripts[payload.operation] = [dict(step) for step in payload.steps]
    return {"operation": payload.operation, "steps": len(payload.steps)}


@app.get("/internal/test/state")
async def get_state(x_control_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_control(x_control_key)
    async with state.lock:
        return {
            "provider_channel_id": state.provider_channel_id,
            "balances": {
                f"{channel}:{user}": value
                for (channel, user), value in state.balances.items()
            },
            "scripts": {key: len(value) for key, value in state.scripts.items()},
        }


@app.get("/internal/test/requests")
async def get_requests(x_control_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_control(x_control_key)
    async with state.lock:
        return {"requests": list(state.requests)}
