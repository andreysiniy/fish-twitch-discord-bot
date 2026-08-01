from app.bot import FisherDiscordBot
from app.config import settings
from app.logging import configure_logging


def main() -> None:
    configure_logging(settings.LOG_LEVEL)
    bot = FisherDiscordBot(settings)
    bot.run(settings.DISCORD_BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
