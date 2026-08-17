"""Small Redis health helper used by resilience scenarios."""

from __future__ import annotations

import redis.asyncio as redis


class RunnerRedisClient:
    def __init__(self, url: str):
        self.client = redis.from_url(url, decode_responses=True)

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    async def close(self) -> None:
        await self.client.aclose()

