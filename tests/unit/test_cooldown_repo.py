from datetime import datetime, timedelta, timezone

from infrastructure.repositories.cooldown_repo import CooldownRepository


class _BrokenRedis:
    def ttl(self, _key):
        raise ConnectionError("redis unavailable")


def test_cooldown_falls_back_to_durable_cast_deadline(monkeypatch) -> None:
    deadline = datetime.now(timezone.utc) + timedelta(seconds=7)
    repository = CooldownRepository(redis_client=_BrokenRedis(), db=object())
    monkeypatch.setattr(repository, "_durable_next_available_at", lambda *_: deadline)

    active, seconds_left = repository.check_cooldown("channel", "viewer")

    assert active is True
    assert 1 <= seconds_left <= 7


def test_cooldown_without_redis_or_durable_deadline_is_inactive() -> None:
    repository = CooldownRepository(redis_client=None)

    assert repository.check_cooldown("channel", "viewer") == (False, 0)
