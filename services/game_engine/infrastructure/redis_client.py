from threading import Lock

import redis
from redis import Redis

from core.config import settings


class RedisClient:
    _client: Redis | None = None
    _lock = Lock()

    @classmethod
    def get_client(cls) -> Redis:
        if cls._client is None:
            with cls._lock:
                if cls._client is None:
                    cls._client = redis.Redis.from_url(
                        settings.REDIS_URL,
                        decode_responses=True
                    )
        return cls._client
