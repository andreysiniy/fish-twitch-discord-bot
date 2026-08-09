import logging

from action_handler import ActionHandler
from api_client import EngineApiClient
from commands.admin import AdminCog
from commands.economy import EconomyCog
from commands.fishing import FishingCog
from commands.inventory import InventoryCog
from commands.travel import TravelCog
from config import BotConfig
from logging_config import configure_logging
from reconnect_patch import patch_reconnect_init
from twitchio.ext import commands

logger = logging.getLogger(__name__)


class BotGateway(commands.Bot):
    def __init__(self, cfg: BotConfig):
        super().__init__(
            token=cfg.twitch_token,
            prefix=cfg.command_prefix,
            initial_channels=cfg.initial_channels,
            client_secret=cfg.twitch_client_secret or None,
            client_id=cfg.twitch_client_id or None,
            bot_id=cfg.bot_nick or None,
        )
        self.cfg = cfg
        self.api_client = EngineApiClient(cfg.engine_url)
        self.action_handler = ActionHandler(self)
        patch_reconnect_init(self._connection)

        self.add_cog(FishingCog(self))
        self.add_cog(EconomyCog(self))
        self.add_cog(InventoryCog(self))
        self.add_cog(TravelCog(self))
        self.add_cog(AdminCog(self))

    async def event_ready(self):
        logger.info("Twitch bot ready nick=%s engine_url=%s", self.nick, self.cfg.engine_url)
        if not self.cfg.twitch_client_id:
            logger.warning(
                "TWITCH_CLIENT_ID is not set: moderation actions (timeout/ban) "
                "will be rejected by the Twitch API"
            )

    async def event_error(self, error: Exception, data=None):
        logger.exception("Unhandled Twitch bot error", exc_info=error)

    async def close(self):
        await self.action_handler.close()
        await self.api_client.close()
        await super().close()


def main() -> None:
    configure_logging()
    cfg = BotConfig.from_env()
    bot = BotGateway(cfg)
    bot.run()


if __name__ == "__main__":
    main()
