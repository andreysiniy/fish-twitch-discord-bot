import asyncio
import logging
import uuid
from typing import Any, Dict

import aiohttp
from heplers.context_tool import get_channel_id

logger = logging.getLogger(__name__)


class ActionHandler:
    TWITCH_BANS_URL = "https://api.twitch.tv/helix/moderation/bans"

    def __init__(self, bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def handle_engine_response(
        self, ctx, response: Dict[str, Any], *, allow_dupe: bool = True
    ) -> None:
        actions = response.get("actions") or []
        for index, action in enumerate(actions):
            await self._execute_action(ctx, action, index, allow_dupe=allow_dupe)

        chat_message = response.get("chat_message")
        if chat_message and not actions:
            await ctx.send(chat_message)

    async def _execute_action(
        self, ctx, action: Dict[str, Any], index: int, *, allow_dupe: bool
    ) -> None:
        action_type = str(action.get("type", ""))
        try:
            if action_type == "timeout":
                await self._handle_timeout(ctx, action)
            elif action_type == "points":
                await self._handle_points(ctx, action, index)
            elif action_type == "dupe" and allow_dupe:
                await self._handle_dupe(ctx, action)
        except Exception as error:
            logger.exception("Failed to execute action type=%s", action_type)
            await ctx.send(f"Action '{action_type}' failed: {type(error).__name__}")
            return

        action_message = action.get("action_message")
        if action_message:
            await ctx.send(action_message)

    async def _handle_dupe(self, ctx, action: Dict[str, Any]) -> None:
        amount = max(min(int(action.get("amount", 1)), 20), 1)
        delay = max(min(int(action.get("delay", 0)), 60), 0)
        channel_id = await get_channel_id(ctx)
        author = ctx.author
        badges = getattr(author, "badges", None)
        is_subscriber = bool(getattr(author, "is_subscriber", False)) or (
            isinstance(badges, dict) and "subscriber" in badges
        )
        payload = {
            "user_id": str(author.id),
            "username": author.name,
            "channel_id": channel_id,
            "is_mod": bool(getattr(author, "is_mod", False)),
            "is_sub": is_subscriber,
            "bypass_cooldown": True,
        }
        for _ in range(amount):
            if delay:
                await asyncio.sleep(delay)
            response = await self.bot.api_client.fish(payload)
            await self.handle_engine_response(ctx, response, allow_dupe=False)

    async def _handle_timeout(self, ctx, action: Dict[str, Any]) -> None:
        duration = max(min(int(action.get("duration", 60)), 1_209_600), 1)
        target_username = str(action.get("target_user") or "").strip()
        reason = str(action.get("reason") or "Fishing timeout")[:500]
        target_id = await self._resolve_user_id(target_username)
        moderator_id = await self._resolve_bot_user_id()
        broadcaster_id = await get_channel_id(ctx)
        token = self.bot.cfg.twitch_token.removeprefix("oauth:")

        session = await self._get_session()
        async with session.post(
            self.TWITCH_BANS_URL,
            params={"broadcaster_id": broadcaster_id, "moderator_id": moderator_id},
            headers={
                "Authorization": f"Bearer {token}",
                "Client-Id": self.bot.cfg.twitch_client_id,
                "Content-Type": "application/json",
            },
            json={"data": {"user_id": target_id, "duration": duration, "reason": reason}},
        ) as response:
            if response.status >= 400:
                raise RuntimeError(f"Twitch moderation API returned {response.status}")

    async def _handle_points(self, ctx, action: Dict[str, Any], index: int) -> None:
        channel_id = await get_channel_id(ctx)
        message = getattr(ctx, "message", None)
        message_id = str(getattr(message, "id", "") or uuid.uuid4())
        await self.bot.api_client.execute_points_action(
            channel_id=channel_id,
            target_username=str(action.get("target_user") or ctx.author.name),
            amount=int(action.get("amount", 0)),
            idempotency_key=f"twitch:{message_id}:action:{index}",
        )

    async def _resolve_user_id(self, username: str) -> str:
        users = await self.bot.fetch_users(names=[username])
        if not users:
            raise ValueError("Twitch user not found")
        return str(users[0].id)

    async def _resolve_bot_user_id(self) -> str:
        user_id = getattr(self.bot, "user_id", None)
        if user_id:
            return str(user_id)
        return await self._resolve_user_id(self.bot.cfg.bot_nick)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self._session
