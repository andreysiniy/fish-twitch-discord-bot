from redis import Redis


class CooldownRepository:
    KEY_TEMPLATE = "cd:fish:{channel_id}:{user_id}"

    def __init__(self, redis_client: Redis):
        self.redis_client = redis_client

    def check_cooldown(self, channel_id: str, user_id: str) -> tuple[bool, int]:
        key = self.KEY_TEMPLATE.format(channel_id=channel_id, user_id=user_id)
        ttl = int(self.redis_client.ttl(key))

        if ttl > 0:
            return True, ttl

        if ttl in (0, -1):
            is_active = bool(self.redis_client.exists(key))
            return is_active, 0

        return False, 0

    def set_cooldown(self, channel_id: str, user_id: str, duration: int) -> None:
        if duration <= 0:
            return

        key = self.KEY_TEMPLATE.format(channel_id=channel_id, user_id=user_id)
        self.redis_client.set(key, 1, ex=duration)
