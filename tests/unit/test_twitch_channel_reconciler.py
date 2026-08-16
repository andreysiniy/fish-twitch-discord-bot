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
        self.calls = 0
        self.second_call = asyncio.Event()

    async def desired_twitch_channels(self):
        self.calls += 1
        if self.calls == 2:
            self.second_call.set()
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


def test_database_membership_does_not_treat_bootstrap_entry_as_joined() -> None:
    async def scenario():
        bot = FakeBot()
        api = FakeApi([{"channels": [{"twitch_id": "1", "login": "alpha"}]}])
        config = _config()
        config.bootstrap_channels = ["alpha"]
        reconciler = TwitchChannelReconciler(bot, api, config)

        assert await reconciler.reconcile_once()
        assert bot.joins == ["alpha"]

    asyncio.run(scenario())


def test_reconcile_uses_runtime_membership_for_join_and_part() -> None:
    async def scenario():
        bot = FakeBot()
        bot.connected_channels = ["alpha", "stale"]
        api = FakeApi([{"channels": [{"twitch_id": "1", "login": "alpha"}]}])
        reconciler = TwitchChannelReconciler(bot, api, _config())

        assert await reconciler.reconcile_once()
        assert bot.joins == []
        assert bot.parts == ["stale"]
        assert reconciler._joined == {"1": "alpha"}

    asyncio.run(scenario())


def test_start_wakes_existing_loop_after_twitch_reconnect() -> None:
    async def scenario():
        bot = FakeBot()
        api = FakeApi(
            [
                {"channels": [{"twitch_id": "1", "login": "alpha"}]},
                {"channels": [{"twitch_id": "1", "login": "alpha"}]},
            ]
        )
        config = _config()
        config.channel_reconcile_seconds = 60
        reconciler = TwitchChannelReconciler(bot, api, config)

        await reconciler.start()
        assert api.calls == 1
        await reconciler.start()
        await asyncio.wait_for(api.second_call.wait(), timeout=1)
        await reconciler.stop()

        assert api.calls == 2
        assert bot.joins == ["alpha", "alpha"]

    asyncio.run(scenario())
