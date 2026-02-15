from typing import Optional

from twitchio.ext import commands

from api_client import EngineApiError

from heplers.context_tool import get_channel_id


class TravelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="fishtravel")
    async def fishtravel(self, ctx: commands.Context, location_number: Optional[int] = None) -> None:
        channel_id = await get_channel_id(ctx)
        payload = {
            "user_id": str(ctx.author.id),
            "username": ctx.author.name,
            "channel_id": channel_id,
            "location_number": location_number,
        }
        try:
            response = await self.bot.api_client.fish_travel(payload)
            await ctx.send(response.get("chat_message", "Travel processed."))
        except EngineApiError as error:
            await ctx.send(f"Travel error: {error}")
        except Exception as error:
            print(f"[fishtravel] unexpected error: {error}")
            await ctx.send("Could not process travel action.")
