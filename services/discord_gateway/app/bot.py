import logging

import discord
from discord import app_commands
from redis.asyncio import Redis
from redis.asyncio import from_url as redis_from_url
from redis.exceptions import RedisError

from app.api.admin import AdminApi
from app.api.client import EngineClient
from app.api.errors import EngineError, localize_error
from app.commands import register_commands
from app.config import DiscordSettings
from app.health import HealthServer
from app.interactions.sessions import WizardSessionStore

logger = logging.getLogger(__name__)


class FisherDiscordBot(discord.Client):
    def __init__(self, settings: DiscordSettings):
        intents = discord.Intents.none()
        intents.message_content = False
        super().__init__(intents=intents)
        self.settings = settings
        self.tree = app_commands.CommandTree(self)
        self.engine = EngineClient(settings)
        self.redis: Redis = redis_from_url(settings.REDIS_URL, decode_responses=True)
        self.sessions = WizardSessionStore(self.redis, settings.WIZARD_SESSION_TTL_SECONDS)
        self.api = AdminApi(self.engine)
        self.commands_synced = False
        self.health = HealthServer(settings.HEALTH_PORT, self.readiness)
        register_commands(self.tree, self.api, self.sessions)
        self.tree.on_error = self.on_tree_error

    async def setup_hook(self) -> None:
        await self.engine.start()
        await self.health.start()
        if self.settings.COMMAND_SYNC_MODE == "guild":
            if not self.settings.DEV_GUILD_ID:
                raise RuntimeError("DEV_GUILD_ID is required for guild command sync")
            guild = discord.Object(id=self.settings.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
        else:
            synced = await self.tree.sync()
        self.commands_synced = True
        logger.info("Application commands synchronized", extra={"command_count": len(synced)})

    async def on_ready(self) -> None:
        logger.info(
            "Discord gateway ready",
            extra={"discord_user_id": str(self.user.id if self.user else "")},
        )

    async def on_tree_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        cause = getattr(error, "original", error)
        if isinstance(cause, EngineError):
            message = localize_error(cause)
        elif isinstance(error, app_commands.CheckFailure):
            message = "This command is not available in the current context."
        else:
            logger.exception(
                "Unhandled interaction error",
                exc_info=error,
                extra={
                    "interaction_id": str(interaction.id),
                    "discord_user_id": str(interaction.user.id),
                    "discord_guild_id": str(interaction.guild_id or ""),
                },
            )
            message = "The operation could not be completed. Please try again."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def readiness(self) -> dict[str, bool]:
        try:
            redis_ready = bool(await self.redis.ping())
        except RedisError as error:
            logger.warning(
                "Redis readiness check failed", extra={"error_type": type(error).__name__}
            )
            redis_ready = False
        return {
            "discord": self.is_ready(),
            "redis": redis_ready,
            "game_engine": await self.engine.health(),
            "commands": self.commands_synced,
        }

    async def close(self) -> None:
        await self.health.close()
        await self.engine.close()
        await self.redis.aclose()
        await super().close()
