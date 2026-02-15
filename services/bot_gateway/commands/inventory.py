from twitchio.ext import commands

from api_client import EngineApiError

from heplers.context_tool import get_channel_id

class InventoryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="fishbag")
    async def fishbag(self, ctx: commands.Context) -> None:
        channel_id = await get_channel_id(ctx)
        try:
            response = await self.bot.api_client.get_inventory(
                channel_id=channel_id,
                user_id=str(ctx.author.id)
            )
            await self._send_inventory(ctx, response)
        except EngineApiError as error:
            await ctx.send(f"Inventory error: {error}")
        except Exception as error:
            print(f"[fishbag] unexpected error: {error}")
            await ctx.send("Could not retrieve inventory.")

    @commands.command(name="fishequip")
    async def fishequip(self, ctx: commands.Context, slot_id: int | None = None) -> None:
        channel_id = await get_channel_id(ctx)
        payload = {
            "user_id": str(ctx.author.id),
            "channel_id": channel_id,
            "slot_id": slot_id,
        }
        try:
            response = await self.bot.api_client.equip_item(payload)
            await ctx.send(response.get("message", "Item equipped."))
        except EngineApiError as error:
            await ctx.send(f"Equip error: {error}")
        except Exception as error:
            print(f"[fishequip] unexpected error: {error}")
            await ctx.send("Could not equip item.")

    async def _send_inventory(self, ctx: commands.Context, response: dict) -> None:
        items = response.get("items", [])
        if not items:
            await ctx.send("Inventory is empty.")
            return

        lines = []
        for item in items[:8]:
            slot_id = item.get("slot_id", "?")
            name = item.get("name", "Unknown")
            qty = item.get("quantity", 1)
            lines.append(f"[{slot_id}] {name} x{qty}")

        message = "Inventory: " + ", ".join(lines)
        await ctx.send(message)
