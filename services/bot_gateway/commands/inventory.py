import logging

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
        except Exception:
            logger.exception("Fish inventory command failed")
            await ctx.send("Could not retrieve inventory.")

    @commands.command(name="fishequip")
    async def fishequip(self, ctx: commands.Context, slot_id: str | None = None) -> None:
        channel_id = await get_channel_id(ctx)
        try:
            parsed_slot = int(slot_id) if slot_id else None
        except ValueError:
            # Non-numeric input: the engine answers with the usage message.
            parsed_slot = None
        payload = {
            "user_id": str(ctx.author.id),
            "channel_id": channel_id,
            "slot_id": parsed_slot,
        }
        try:
            response = await self.bot.api_client.equip_item(payload)
            await ctx.send(response.get("message", "Item equipped."))
        except EngineApiError as error:
            await ctx.send(f"Equip error: {error}")
        except Exception:
            logger.exception("Fish equip command failed")
            await ctx.send("Could not equip item.")

    async def _send_inventory(self, ctx: commands.Context, response: dict) -> None:
        items = response.get("items", [])
        if not items:
            await ctx.send("Inventory is empty.")
            return

        max_slots = int(response.get("max_slots") or 0)
        lines = []
        for item in items[:8]:
            slot_id = item.get("slot_id", "?")
            name = item.get("title", "Unknown")
            qty = item.get("quantity", 1)
            durability = ""
            max_durability = item.get("max_durability")
            if max_durability is not None:
                current = item.get("current_durability")
                durability = f" (durability {current}/{max_durability})"
            lines.append(f"[{slot_id}] {name} x{qty}{durability}")

        header = f"Inventory {len(items)}/{max_slots} slots: " if max_slots else "Inventory: "
        message = header + ", ".join(lines)
        await ctx.send(message)
logger = logging.getLogger(__name__)
