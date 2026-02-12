from twitchio.ext import commands

from action_handler import ActionHandler
from api_client import EngineApiClient
from commands.fishing import FishingCog
from commands.inventory import InventoryCog
from commands.travel import TravelCog
from config import BotConfig


class BotGateway(commands.Bot):
    def __init__(self, cfg: BotConfig):
        super().__init__(
            token=cfg.twitch_token,
            prefix=cfg.command_prefix,
            initial_channels=cfg.initial_channels,
            client_secret=cfg.twitch_client_secret or None,
            client_id=cfg.twitch_client_id or None,
            bot_id=cfg.bot_nick or None
        )
        self.cfg = cfg
        self.api_client = EngineApiClient(cfg.engine_url)
        self.action_handler = ActionHandler()

        self.add_cog(FishingCog(self))
        self.add_cog(InventoryCog(self))
        self.add_cog(TravelCog(self))

    def resolve_channel_id(self, ctx: commands.Context) -> str:
        channel = getattr(ctx, "channel", None)
        if channel is None:
            return ""

        for attr in ("id", "channel_id", "broadcaster_id"):
            value = getattr(channel, attr, None)
            if value is not None and str(value).strip():
                return str(value)

        broadcaster = getattr(ctx, "broadcaster", None)
        if broadcaster is not None:
            value = getattr(broadcaster, "id", None)
            if value is not None and str(value).strip():
                return str(value)

        # Fallback for unexpected context shapes.
        return str(getattr(channel, "name", "")).strip()

    async def event_ready(self):
        print(f"Logged in as | {self.nick}")
        print(f"Engine URL    | {self.cfg.engine_url}")

    async def event_error(self, error: Exception, data=None):
        print(f"[bot-error] {error}")

    async def close(self):
        await self.api_client.close()
        await super().close()


def main() -> None:
    cfg = BotConfig.from_env()
    bot = BotGateway(cfg)
    bot.run()


if __name__ == "__main__":
    main()
