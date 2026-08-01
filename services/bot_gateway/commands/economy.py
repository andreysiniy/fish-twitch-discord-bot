import logging

from twitchio.ext import commands

from api_client import EngineApiError
from heplers.context_tool import get_channel_id


class EconomyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="fishsell")
    async def fishsell(self, ctx: commands.Context, amount: str | None = None) -> None:
        channel_id = await get_channel_id(ctx)
        payload = {
            "user_id": str(ctx.author.id),
            "username": ctx.author.name,
            "channel_id": channel_id,
            "user_input": amount,
        }
        try:
            response = await self.bot.api_client.sell_fish(payload)
            await ctx.send(response.get("chat_message", "Sell action processed."))
        except EngineApiError as error:
            await ctx.send(f"Economy error: {error}")
        except Exception as error:
            logger.exception("Fish sell command failed")
            await ctx.send("Could not sell fish.")

    @commands.command(name="fishbuy")
    async def fishbuy(self, ctx: commands.Context, amount: str | None = None) -> None:
        channel_id = await get_channel_id(ctx)
        payload = {
            "user_id": str(ctx.author.id),
            "username": ctx.author.name,
            "channel_id": channel_id,
            "user_input": amount,
        }
        try:
            response = await self.bot.api_client.buy_fish(payload)
            await ctx.send(response.get("chat_message", "Buy action processed."))
        except EngineApiError as error:
            await ctx.send(f"Economy error: {error}")
        except Exception as error:
            logger.exception("Fish buy command failed")
            await ctx.send("Could not buy fish.")
logger = logging.getLogger(__name__)
