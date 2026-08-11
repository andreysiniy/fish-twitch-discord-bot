from datetime import datetime, timezone
from math import ceil

from redis import Redis
from sqlalchemy import desc
from sqlalchemy.orm import Session

from infrastructure.models import Channel, FishingCast


class CooldownRepository:
    KEY_TEMPLATE = "cd:fish:{channel_id}:{user_id}"

    def __init__(self, redis_client: Redis | None, db: Session | None = None):
        self.redis_client = redis_client
        self.db = db

    def _durable_next_available_at(self, channel_id: str, user_id: str) -> datetime | None:
        if self.db is None:
            return None
        try:
            row = (
                self.db.query(FishingCast.next_available_at)
                .join(Channel, Channel.id == FishingCast.channel_id)
                .filter(
                    Channel.twitch_id == str(channel_id),
                    FishingCast.twitch_user_id_snapshot == str(user_id),
                    FishingCast.status == "resolved",
                    FishingCast.next_available_at.is_not(None),
                )
                .order_by(desc(FishingCast.next_available_at))
                .first()
            )
        except Exception:
            return None
        return row[0] if row else None

    def next_available_at(self, channel_id: str, user_id: str) -> datetime | None:
        return self._durable_next_available_at(channel_id, user_id)

    def check_cooldown(self, channel_id: str, user_id: str) -> tuple[bool, int]:
        key = self.KEY_TEMPLATE.format(channel_id=channel_id, user_id=user_id)
        try:
            ttl = int(self.redis_client.ttl(key)) if self.redis_client is not None else -2
            if ttl > 0:
                return True, ttl
            if ttl in (0, -1) and bool(self.redis_client.exists(key)):
                return True, 0
        except Exception:
            pass

        next_available = self._durable_next_available_at(channel_id, user_id)
        if next_available is None:
            return False, 0
        if next_available.tzinfo is None:
            next_available = next_available.replace(tzinfo=timezone.utc)
        seconds_left = ceil((next_available - datetime.now(timezone.utc)).total_seconds())
        return (True, max(seconds_left, 0)) if seconds_left > 0 else (False, 0)

    def set_cooldown(self, channel_id: str, user_id: str, duration: int) -> None:
        if duration <= 0:
            return

        if self.redis_client is not None:
            key = self.KEY_TEMPLATE.format(channel_id=channel_id, user_id=user_id)
            self.redis_client.set(key, 1, ex=duration)
