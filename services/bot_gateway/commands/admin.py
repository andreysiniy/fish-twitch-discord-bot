import logging
import unicodedata

from twitchio.ext import commands
from twitchio import User

from heplers.context_tool import get_channel_id

from api_client import EngineApiError

ALLOWED_ROLES = {"editor", "moderator"}
# TwitchIO may expose the missing optional argument as the string "0".
INDEFINITE_DURATION_TOKENS = {"", "0", "none", "null", "indefinite", "unlimited"}
logger = logging.getLogger(__name__)


def _duration_argument(arg2: str | None) -> str:
    """Read duration from the second command token without parser defaults."""
    if not isinstance(arg2, str):
        return ""
    return _strip_invisible_characters(arg2)


def _optional_duration_seconds(arg2: str | None) -> int | None:
    token = _duration_argument(arg2)
    if token.casefold() in INDEFINITE_DURATION_TOKENS:
        return None
    try:
        value = int(token)
    except (TypeError, ValueError):
        logger.warning(
            "Ignoring an invalid optional fishevent duration token",
            extra={"duration_token": token},
        )
        return None
    if value <= 0:
        logger.warning(
            "Ignoring a non-positive optional fishevent duration token",
            extra={"duration_token": token},
        )
        return None
    return value


def _strip_invisible_characters(value: str) -> str:
    return "".join(
        char
        for char in value
        if not char.isspace() and unicodedata.category(char)[0] not in {"C", "Z"}
    ).strip()


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
        except Exception:
            logger.exception("Moderator list command failed")
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
        except Exception:
            logger.exception("Moderator add command failed")
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
        except Exception:
            logger.exception("Moderator remove command failed")
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
        if isinstance(arg1, str) and arg1.strip().lower() == "set":
            if arg2 is None:
                await ctx.send("Usage: !fishcd set <seconds> [sub]")
                return

            try:
                seconds_value = int(arg2)
                if seconds_value < 0:
                    raise ValueError
            except ValueError:
                await ctx.send("Seconds must be a non-negative integer")
                return

            normalized_scope = (arg3 or "").strip().lower()
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
            except Exception:
                logger.exception("Cooldown update command failed")
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
        except Exception:
            logger.exception("Cooldown status command failed")
            await ctx.send("Could not retrieve cooldown")

    @commands.command(name="fishevent")
    async def fishevent(self, ctx: commands.Context, *args: str) -> None:
        channel_id = await get_channel_id(ctx)
        actor_id = str(ctx.author.id)
        arg1 = args[0] if args else None
        arg2 = args[1] if len(args) > 1 else None

        if not arg1:
            try:
                response = await self.bot.api_client.admin_list_fishing_events(
                    channel_id=channel_id,
                    actor_twitch_id=actor_id
                )
                await ctx.send(response.get("chat_message", "Available events: none"))
            except EngineApiError as error:
                await ctx.send(str(error))
            except Exception:
                logger.exception("Fishing event list command failed")
                await ctx.send("Could not load events")
            return

        try:
            event_number = int(arg1)
            if event_number <= 0:
                raise ValueError
        except ValueError:
            await ctx.send("Usage: !fishevent <event_number> [duration_seconds]")
            return

        duration_seconds = _optional_duration_seconds(arg2)

        try:
            response = await self.bot.api_client.admin_toggle_fishing_event(
                channel_id=channel_id,
                actor_twitch_id=actor_id,
                event_number=event_number,
                duration_seconds=duration_seconds
            )
            status = str(response.get("status", "")).lower()
            event = response.get("event") or {}
            title = event.get("event_title", "Untitled Event")
            eid = event.get("id", event_number)
            scheduled_at = response.get("scheduled_disable_at")
            chat_message = response.get("chat_message")

            if chat_message:
                await ctx.send(chat_message)
                return

            if status == "deactivated":
                await ctx.send(f"Event disabled: [{eid}] {title}")
                return

            if scheduled_at:
                await ctx.send(
                    f"Event enabled: [{eid}] {title}. Auto-disable scheduled at unix={scheduled_at}"
                )
                return

            await ctx.send(f"Event enabled: [{eid}] {title}")
        except EngineApiError as error:
            await ctx.send(str(error))
        except Exception:
            logger.exception("Fishing event toggle command failed")
            await ctx.send("Could not toggle event")

    @commands.command(name="fisheconomy")
    async def fisheconomy(self, ctx: commands.Context, *args: str) -> None:
        """Toggle StreamElements economy switches for the channel."""
        channel_id = await get_channel_id(ctx)
        action = "_".join(part.strip().lower() for part in args if part.strip())
        aliases = {"buy_on": "buy_on", "buy_off": "buy_off", "sell_on": "sell_on", "sell_off": "sell_off"}
        if action in {"on", "off", "status"}:
            normalized = action
        else:
            normalized = aliases.get(action, "")
        if not normalized:
            await ctx.send(
                "Usage: !fisheconomy on|off|buy on|buy off|sell on|sell off|status"
            )
            return
        try:
            result = await self.bot.api_client.admin_economy_switch(
                channel_id=channel_id,
                actor_twitch_id=str(ctx.author.id),
                action=normalized,
            )
            await ctx.send(
                "Economy switches: "
                f"conversions {'on' if result.get('enabled') else 'off'}, "
                f"buy {'on' if result.get('buy_enabled') else 'off'}, "
                f"sell {'on' if result.get('sell_enabled') else 'off'}."
            )
        except EngineApiError as error:
            await ctx.send(str(error))
        except Exception:
            logger.exception("Economy switch command failed")
            await ctx.send("Could not update economy switches")

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
