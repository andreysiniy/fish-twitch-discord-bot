import json
import uuid
from typing import Any

from redis.asyncio import Redis


class WizardSessionStore:
    def __init__(self, redis: Redis, ttl_seconds: int = 900):
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def create(self, discord_user_id: int | str, data: dict[str, Any]) -> str:
        flow_id = str(uuid.uuid4())
        await self.redis.setex(
            self._key(discord_user_id, flow_id),
            self.ttl_seconds,
            json.dumps(data, ensure_ascii=False),
        )
        return flow_id

    async def get(self, discord_user_id: int | str, flow_id: str) -> dict[str, Any] | None:
        raw = await self.redis.get(self._key(discord_user_id, flow_id))
        return json.loads(raw) if raw else None

    async def update(self, discord_user_id: int | str, flow_id: str, data: dict[str, Any]) -> None:
        key = self._key(discord_user_id, flow_id)
        if not await self.redis.exists(key):
            raise KeyError("Wizard session expired")
        await self.redis.setex(key, self.ttl_seconds, json.dumps(data, ensure_ascii=False))

    async def delete(self, discord_user_id: int | str, flow_id: str) -> None:
        await self.redis.delete(self._key(discord_user_id, flow_id))

    def _key(self, discord_user_id: int | str, flow_id: str) -> str:
        return f"fish:discord:session:{discord_user_id}:{flow_id}"
