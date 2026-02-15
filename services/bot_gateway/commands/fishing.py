from twitchio.ext import commands

from heplers.context_tool import get_channel_id

from api_client import EngineApiError


class FishingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="fish")
    async def fish(self, ctx: commands.Context) -> None:
        channel_id = await get_channel_id(ctx)
        payload = {
            "user_id": str(ctx.author.id),
            "username": ctx.author.name,
            "channel_id": channel_id,
            "is_mod": bool(getattr(ctx.author, "is_mod", False)),
            "is_sub": self._resolve_is_subscriber(ctx),
        }
        try:
            response = await self.bot.api_client.fish(payload)
            await self.bot.action_handler.handle_engine_response(ctx, response)
        except EngineApiError as error:
            await ctx.send(f"Engine error: {error}")
        except Exception as error:
            print(f"[fish] unexpected error: {error}")
            await ctx.send("Could not process fishing action.")

    def _resolve_is_subscriber(self, ctx: commands.Context) -> bool:
        explicit_flag = getattr(ctx.author, "is_subscriber", None)
        if explicit_flag is not None:
            return bool(explicit_flag)

        badges = getattr(ctx.author, "badges", None)
        if isinstance(badges, dict):
            return "subscriber" in badges

        return False
