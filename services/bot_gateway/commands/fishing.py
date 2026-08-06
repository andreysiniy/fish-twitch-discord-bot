import logging
from datetime import datetime, timezone

from twitchio.ext import commands
from twitchio import User

from heplers.context_tool import get_channel_id

from api_client import EngineApiError


class FishingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="fish")
    async def fish(self, ctx: commands.Context) -> None:
        channel_id = await get_channel_id(ctx)
        message_id = getattr(getattr(ctx, "message", None), "id", None)
        source_request_id = f"twitch-{message_id}" if message_id else None
        payload = {
            "user_id": str(ctx.author.id),
            "username": ctx.author.name,
            "channel_id": channel_id,
            "is_mod": bool(getattr(ctx.author, "is_mod", False)),
            "is_sub": self._resolve_is_subscriber(ctx),
            "source": "twitch",
            "source_request_id": source_request_id,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            response = await self.bot.api_client.fish(payload)
            await self.bot.action_handler.handle_engine_response(ctx, response)
        except EngineApiError as error:
            await ctx.send(f"Engine error: {error}")
        except Exception:
            logger.exception("Fish command failed")
            await ctx.send("Could not process fishing action.")

    def _resolve_is_subscriber(self, ctx: commands.Context) -> bool:
        explicit_flag = getattr(ctx.author, "is_subscriber", None)
        if explicit_flag is not None:
            return bool(explicit_flag)

        badges = getattr(ctx.author, "badges", None)
        if isinstance(badges, dict):
            return "subscriber" in badges

        return False

    @commands.command(name="fishstats")
    async def fishstats(self, ctx: commands.Context, user: User | None = None) -> None:
        channel_id = await get_channel_id(ctx)
        target_user = user or ctx.author
        target_user_id = str(target_user.id)
        target_username = target_user.name
        try:
            response = await self.bot.api_client.fish_stats(
                channel_id=channel_id,
                user_id=target_user_id,
                username=target_username
            )
            await ctx.send(response.get("chat_message", "Stats are unavailable."))
        except EngineApiError as error:
            await ctx.send(f"Stats error: {error}")
        except Exception:
            logger.exception("Fish stats command failed")
            await ctx.send("Could not retrieve stats.")

    @commands.command(name="fishtop")
    async def fishtop(self, ctx: commands.Context, mode: str | None = None) -> None:
        channel_id = await get_channel_id(ctx)
        normalized_mode = (mode or "current").strip().lower()
        if normalized_mode not in {"current", "alltime", "catches", "level"}:
            await ctx.send("Usage: !fishtop [alltime|catches|level]")
            return
        try:
            response = await self.bot.api_client.fish_top(
                channel_id=channel_id,
                limit=10,
                mode=normalized_mode
            )
            await ctx.send(response.get("chat_message", "Top is unavailable."))
        except EngineApiError as error:
            await ctx.send(f"Top error: {error}")
        except Exception:
            logger.exception("Fish top command failed")
            await ctx.send("Could not retrieve top players.")
logger = logging.getLogger(__name__)
