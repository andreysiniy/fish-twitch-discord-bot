import logging

from api_client import EngineApiError
from heplers.context_tool import get_channel_id
from twitchio.ext import commands


def _user_economy_error(error: EngineApiError) -> str:
    """Keep internal provider details out of public Twitch chat errors."""

    if error.code == "ECONOMY_OPERATION_IN_PROGRESS":
        return str(error)
    if error.code and (
        error.code.startswith("STREAM_ELEMENTS") or error.code == "ECONOMY_PROVIDER_ERROR"
    ):
        return "The fish market is temporarily unavailable. Please try again later."
    return str(error)


class EconomyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="fishsell")
    async def fishsell(self, ctx: commands.Context, amount: str | None = None) -> None:
        channel_id = await get_channel_id(ctx)
        message_id = str(getattr(ctx.message, "id", ""))
        payload = {
            "user_id": str(ctx.author.id),
            "username": ctx.author.name,
            "channel_id": channel_id,
            "user_input": amount,
            "source_request_id": message_id,
        }
        try:
            key = f"twitch:{channel_id}:{message_id}:fishsell"
            response = await self.bot.api_client.sell_fish(payload, idempotency_key=key)
            await ctx.send(response.get("chat_message", "Sell action processed."))
        except EngineApiError as error:
            await ctx.send(_user_economy_error(error))
        except Exception:
            logger.exception("Fish sell command failed")
            await ctx.send("Could not sell fish.")

    @commands.command(name="fishbuy")
    async def fishbuy(self, ctx: commands.Context, amount: str | None = None) -> None:
        channel_id = await get_channel_id(ctx)
        message_id = str(getattr(ctx.message, "id", ""))
        payload = {
            "user_id": str(ctx.author.id),
            "username": ctx.author.name,
            "channel_id": channel_id,
            "user_input": amount,
            "source_request_id": message_id,
        }
        try:
            key = f"twitch:{channel_id}:{message_id}:fishbuy"
            response = await self.bot.api_client.buy_fish(payload, idempotency_key=key)
            await ctx.send(response.get("chat_message", "Buy action processed."))
        except EngineApiError as error:
            await ctx.send(_user_economy_error(error))
        except Exception:
            logger.exception("Fish buy command failed")
            await ctx.send("Could not buy fish.")

    @commands.command(name="fishrate")
    async def fishrate(self, ctx: commands.Context) -> None:
        channel_id = await get_channel_id(ctx)
        try:
            result = await self.bot.api_client.fish_rate(channel_id)
            await ctx.send(
                f"Fish rate: buy {result.get('buy_points_per_kg')} points/kg, "
                f"sell {result.get('sell_points_per_kg')} points/kg."
            )
        except EngineApiError as error:
            await ctx.send(_user_economy_error(error))
        except Exception:
            logger.exception("Fish rate command failed")
            await ctx.send("Could not load the fish rate.")


logger = logging.getLogger(__name__)
