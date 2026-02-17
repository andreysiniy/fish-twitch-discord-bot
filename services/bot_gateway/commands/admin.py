from twitchio.ext import commands
from twitchio import User
from typing import Literal

from heplers.context_tool import get_channel_id

from api_client import EngineApiError

ALLOWED_ROLES = {"editor", "moderator"}


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="fishmods")
    async def fishmods(self, ctx: commands.Context) -> None:
        channel_id = await get_channel_id(ctx)
        actor_id = str(ctx.author.id)

        try:
            response = await self.bot.api_client.admin_list_moderators(
                channel_id=channel_id,
                actor_twitch_id=actor_id
            )
            records = response.get("items", [])
            if not records:
                await ctx.send("No moderators configured")
                return

            chunks = [
                f"{record.get('user_twitch_name', 'unknown')}:{record.get('role', 'unknown')}"
                for record in records[:8]
            ]
            await ctx.send("Moderators: " + ", ".join(chunks))
        except EngineApiError as error:
            await ctx.send(f"Admin error: {error}")
        except Exception as error:
            print(f"[fishmods] unexpected error: {error}")
            await ctx.send("Could not load moderators")

    @commands.command(name="fishmodadd")
    async def fishmodadd(
        self,
        ctx: commands.Context,
        user: User | None = None,
        role: str = "moderator"
    ) -> None:
        channel_id = await get_channel_id(ctx)
        actor_id = str(ctx.author.id)
        if not self._is_channel_owner(actor_id, channel_id):
            await ctx.send("Only channel owner can use this command")
            return
        if not user:
            await ctx.send("Usage: !fishmodadd <username> [moderator|editor]")
            return

        user_twitch_id = str(user.id)
        normalized_role = role.strip().lower()
        if normalized_role not in ALLOWED_ROLES:
            await ctx.send("Role must be moderator or editor")
            return

        try:
            response = await self.bot.api_client.admin_upsert_moderator(
                channel_id=channel_id,
                actor_twitch_id=actor_id,
                user_twitch_id=user_twitch_id,
                user_twitch_name=user.name,
                role=normalized_role
            )
            await ctx.send(
                f"Access updated: {response.get('user_twitch_name', user.name)} "
                f"as {response.get('role', normalized_role)}"
            )
        except EngineApiError as error:
            await ctx.send(f"Admin error: {error}")
        except Exception as error:
            print(f"[fishmodadd] unexpected error: {error}")
            await ctx.send("Could not update moderator.")

    @commands.command(name="fishmoddel")
    async def fishmoddel(self, ctx: commands.Context, user: User | None = None) -> None:
        channel_id = await get_channel_id(ctx)
        actor_id = str(ctx.author.id)
        if not self._is_channel_owner(actor_id, channel_id):
            await ctx.send("Only channel owner can use this command")
            return
        if not user:
            await ctx.send("Usage: !fishmoddel <username>")
            return
        user_twitch_id = str(user.id)
        try:
            await self.bot.api_client.admin_remove_moderator(
                channel_id=channel_id,
                actor_twitch_id=actor_id,
                user_twitch_id=user_twitch_id
            )
            await ctx.send(f"Access removed for {user.name}")
        except EngineApiError as error:
            await ctx.send(f"Admin error: {error}")
        except Exception as error:
            print(f"[fishmoddel] unexpected error: {error}")
            await ctx.send("Could not remove moderator")

    @commands.command(name="fishcd")
    async def fishcd(
        self,
        ctx: commands.Context,
        arg1: User | str | None = None,
        arg2: str | None = None,
        arg3: str | None = None,
        arg4: str | None = None
    ) -> None:
        channel_id = await get_channel_id(ctx)
        print(f"[fishcd] command invoked by {ctx.author.name} with arg1={arg1} arg2={arg2} arg3={arg3} arg4={arg4}")
        if isinstance(arg2, str) and arg2.strip().lower() == "set":
            print(f"[fishcd:set] command invoked by {ctx.author.name} with arg1={arg1} arg2={arg2} arg3={arg3} arg4={arg4}")
            if arg3 is None:
                await ctx.send("Usage: !fishcd set <seconds> [sub]")
                return

            try:
                seconds_value = int(arg3)
                if seconds_value < 0:
                    raise ValueError
            except ValueError:
                await ctx.send("Seconds must be a non-negative integer")
                return

            normalized_scope = (arg4 or "").strip().lower()
            if normalized_scope not in {"", "sub"}:
                await ctx.send("Scope must be empty (global) or sub")
                return

            try:
                response = await self.bot.api_client.admin_set_fish_cooldown(
                    channel_id=channel_id,
                    actor_twitch_id=str(ctx.author.id),
                    seconds=seconds_value,
                    scope=normalized_scope or None
                )
                await ctx.send(response.get("chat_message", "Cooldown updated"))
            except EngineApiError as error:
                await ctx.send(str(error))
            except Exception as error:
                print(f"[fishcd:set] unexpected error: {error}")
                await ctx.send("Could not update cooldown")
            return

        if isinstance(arg1, str):
            await ctx.send("Usage: !fishcd [username] | !fishcd set <seconds> [sub]")
            return

        target_user = arg1 or ctx.author
        payload = {
            "user_id": str(target_user.id),
            "username": target_user.name,
            "channel_id": channel_id,
            "is_mod": False if arg1 else bool(getattr(ctx.author, "is_mod", False)),
            "is_sub": False if arg1 else self._resolve_is_subscriber(ctx),
        }
        try:
            response = await self.bot.api_client.fish_cooldown(payload)
            await ctx.send(response.get("chat_message", "Cooldown is unavailable."))
        except EngineApiError as error:
            await ctx.send(str(error))
        except Exception as error:
            print(f"[fishcd] unexpected error: {error}")
            await ctx.send("Could not retrieve cooldown")

    def _resolve_is_subscriber(self, ctx: commands.Context) -> bool:
        explicit_flag = getattr(ctx.author, "is_subscriber", None)
        if explicit_flag is not None:
            return bool(explicit_flag)

        badges = getattr(ctx.author, "badges", None)
        if isinstance(badges, dict):
            return "subscriber" in badges

        return False

    def _is_channel_owner(self, actor_id: str, channel_id: str) -> bool:
        return bool(actor_id and channel_id and actor_id == channel_id)
