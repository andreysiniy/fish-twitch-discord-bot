import asyncio
import json
import logging
import time
import uuid
from typing import Any, ClassVar

import aiohttp
import discord

from app.api.errors import EngineError
from app.config import DiscordSettings

logger = logging.getLogger(__name__)


class EngineClient:
    RETRY_STATUSES: ClassVar[frozenset[int]] = frozenset({502, 503, 504})

    def __init__(self, settings: DiscordSettings):
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                total=self.settings.HTTP_TIMEOUT_SECONDS,
                connect=2,
                sock_read=5,
            )
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def request(
        self,
        interaction: discord.Interaction,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        await self.start()
        request_id = str(uuid.uuid4())
        headers = self._headers(interaction, request_id, idempotency_key)
        retryable = method.upper() == "GET" or bool(idempotency_key)
        started = time.perf_counter()
        for attempt in range(3):
            try:
                assert self._session is not None
                async with self._session.request(
                    method,
                    f"{self.settings.ENGINE_URL.rstrip('/')}{path}",
                    json=json,
                    headers=headers,
                ) as response:
                    payload = await self._read_json(response)
                    if response.status < 400:
                        self._log_request(interaction, path, response.status, started, request_id)
                        return payload
                    if retryable and response.status in self.RETRY_STATUSES and attempt < 2:
                        await asyncio.sleep(0.2 * (2**attempt))
                        continue
                    self._log_request(
                        interaction,
                        path,
                        response.status,
                        started,
                        request_id,
                    )
                    raise self._engine_error(response.status, payload, request_id)
            except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                if retryable and attempt < 2:
                    await asyncio.sleep(0.2 * (2**attempt))
                    continue
                self._log_request(interaction, path, 503, started, request_id)
                raise EngineError(
                    503,
                    "ENGINE_UNAVAILABLE",
                    "Game engine unavailable",
                    request_id=request_id,
                ) from error
        raise EngineError(
            503, "ENGINE_UNAVAILABLE", "Game engine unavailable", request_id=request_id
        )

    async def health(self) -> bool:
        await self.start()
        try:
            assert self._session is not None
            async with self._session.get(
                f"{self.settings.ENGINE_URL.rstrip('/')}/health/ready"
            ) as response:
                return response.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    def _headers(
        self,
        interaction: discord.Interaction,
        request_id: str,
        idempotency_key: str | None,
    ) -> dict[str, str]:
        guild_id = str(interaction.guild_id) if interaction.guild_id else ""
        permissions = getattr(interaction.user, "guild_permissions", None)
        can_manage = bool(permissions and permissions.manage_guild)
        headers = {
            "X-Service-Name": "discord_gateway",
            "X-Service-API-Key": self.settings.DISCORD_BOT_API_KEY,
            "X-Discord-User-ID": str(interaction.user.id),
            "X-Request-ID": request_id,
            "X-Discord-Manage-Guild": str(can_manage).lower(),
        }
        if guild_id:
            headers["X-Discord-Guild-ID"] = guild_id
        if interaction.channel_id:
            headers["X-Discord-Channel-ID"] = str(interaction.channel_id)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _read_json(self, response: aiohttp.ClientResponse) -> dict[str, Any]:
        try:
            payload = await response.json(content_type=None)
        except (aiohttp.ContentTypeError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {"items": payload}

    def _engine_error(self, status: int, payload: dict, request_id: str) -> EngineError:
        detail = payload.get("detail", payload)
        if isinstance(detail, dict):
            return EngineError(
                status,
                str(detail.get("code") or "ENGINE_ERROR"),
                str(detail.get("message") or "Backend request failed"),
                detail.get("fields") if isinstance(detail.get("fields"), dict) else {},
                str(detail.get("request_id") or request_id),
            )
        return EngineError(status, "ENGINE_ERROR", str(detail), request_id=request_id)

    def _log_request(self, interaction, path, status, started, request_id):
        logger.info(
            "Backend request completed",
            extra={
                "request_id": request_id,
                "interaction_id": str(interaction.id),
                "discord_user_id": str(interaction.user.id),
                "discord_guild_id": str(interaction.guild_id or ""),
                "backend_status": status,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "command": path,
            },
        )
