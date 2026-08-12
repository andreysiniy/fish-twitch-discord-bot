import asyncio

import pytest
from domain.economy import EconomyDomainError
from services.economy_service import EconomyService


class _Redis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, *, nx, ex):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def eval(self, *_args):
        self.values.clear()
        return 1


@pytest.mark.asyncio
async def test_buy_request_lock_rejects_overlapping_viewer_request(monkeypatch):
    redis = _Redis()
    monkeypatch.setattr("services.economy_service.RedisClient.get_client", lambda: redis)
    service = EconomyService.__new__(EconomyService)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def first():
        with service._buy_request_lock("channel", "viewer"):
            entered.set()
            await release.wait()

    task = asyncio.create_task(first())
    await entered.wait()
    with pytest.raises(EconomyDomainError) as error:
        with service._buy_request_lock("channel", "viewer"):
            pass
    assert error.value.code == "ECONOMY_OPERATION_IN_PROGRESS"
    release.set()
    await task
