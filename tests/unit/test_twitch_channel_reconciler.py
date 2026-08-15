import asyncio

from channel_reconciler import TwitchChannelReconciler
from config import BotConfig


class FakeBot:
    def __init__(self):
        self.connected_channels = []
        self.joins = []
        self.parts = []

    async def join_channels(self, channels):
        self.joins.extend(channels)
        self.connected_channels.extend(channels)

    async def part_channels(self, channels):
        self.parts.extend(channels)
        self.connected_channels = [item for item in self.connected_channels if item not in channels]


class FakeApi:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.reports = []

    async def desired_twitch_channels(self):
        payload = next(self.payloads)
        if isinstance(payload, Exception):
            raise payload
        return payload

    async def report_twitch_status(self, payload):
        self.reports.append(payload)
        return {"status": "accepted"}


def _config() -> BotConfig:
    return BotConfig(
        twitch_token="token",
        twitch_client_id="client",
        twitch_client_secret="secret",
        bot_nick="bot",
        bootstrap_channels=[],
        engine_url="http://engine",
        service_api_key="service",
        bot_instance_id="test-instance",
    )


def test_reconcile_is_idempotent_and_parts_removed_channels() -> None:
    async def scenario():
        bot = FakeBot()
        api = FakeApi(
            [
                {"channels": [{"twitch_id": "1", "login": "alpha"}]},
                {"channels": [{"twitch_id": "1", "login": "alpha"}]},
                {"channels": []},
            ]
        )
        reconciler = TwitchChannelReconciler(bot, api, _config())
        assert await reconciler.reconcile_once()
        assert await reconciler.reconcile_once()
        assert bot.joins == ["alpha"]
        assert await reconciler.reconcile_once()
        assert bot.parts == ["alpha"]

    asyncio.run(scenario())


def test_engine_failure_never_parts_current_memberships() -> None:
    async def scenario():
        bot = FakeBot()
        bot.connected_channels = ["alpha"]
        api = FakeApi([RuntimeError("engine unavailable")])
        reconciler = TwitchChannelReconciler(bot, api, _config())
        reconciler._joined = {"stable-id": "alpha"}
        assert not await reconciler.reconcile_once()
        assert bot.parts == []

    asyncio.run(scenario())
