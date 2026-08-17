"""TwitchIO actor sessions and response correlation."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, replace

try:
    from .config import ActorConfig, RunnerSettings
except ImportError:  # pragma: no cover - script-style Docker entrypoint
    from config import ActorConfig, RunnerSettings

try:
    from twitchio import Client
except ModuleNotFoundError:  # pragma: no cover - Docker installs the pinned dependency
    class Client:  # type: ignore[no-redef]
        def __init__(self, **_: object):
            self._channels: dict[str, object] = {}

        async def start(self) -> None:
            raise RuntimeError("twitchio is required for real Twitch E2E mode")

        async def close(self) -> None:
            return None

        async def join_channels(self, channels: list[str]) -> None:
            del channels

        def get_channel(self, channel: str) -> object | None:
            return self._channels.get(channel)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    author_login: str
    author_id: str
    text: str
    message_id: str
    received_at: float
    source_request_id: str = ""


class ActorClient(Client):
    def __init__(self, actor: ActorConfig, cfg: RunnerSettings):
        token = actor.access_token
        if token and not token.startswith("oauth:"):
            token = f"oauth:{token}"
        super().__init__(
            token=token or None,
            client_id=cfg.twitch_client_id or None,
            client_secret=cfg.twitch_client_secret or None,
        )
        self.actor = actor
        self.cfg = cfg
        self.ready = asyncio.Event()
        self.messages: asyncio.Queue[ChatMessage] = asyncio.Queue()
        self.echoes: asyncio.Queue[ChatMessage] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def event_ready(self) -> None:
        self.ready.set()
        if self.cfg.channel:
            await self.join_channels([self.cfg.channel])
        logger.info("E2E actor session ready role=%s login=%s", self.actor.role, self.actor.login)

    async def event_message(self, message) -> None:  # TwitchIO callback signature
        author = getattr(message, "author", None)
        chat_message = ChatMessage(
            author_login=str(getattr(author, "name", "")),
            author_id=str(getattr(author, "id", "")),
            text=str(getattr(message, "content", "")),
            message_id=str(getattr(message, "id", "")),
            received_at=time.monotonic(),
        )
        if getattr(message, "echo", False):
            await self.echoes.put(chat_message)
        else:
            await self.messages.put(chat_message)

    async def start_background(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.start())

    async def stop_background(self) -> None:
        if self._task is not None:
            await self.close()
            try:
                await self._task
            except Exception:
                logger.debug("E2E actor session stopped", exc_info=True)
            self._task = None

    async def send_command(self, command: str) -> str:
        channel = self.get_channel(self.cfg.channel)
        if channel is None:
            raise RuntimeError(f"Actor {self.actor.name} is not joined to the test channel")
        sent = await channel.send(command)
        message_id = str(getattr(sent, "id", sent or ""))
        if message_id:
            return message_id
        try:
            while True:
                echo = await asyncio.wait_for(
                    self.echoes.get(), timeout=self.cfg.command_timeout_seconds
                )
                if echo.text == command:
                    return echo.message_id
        except asyncio.TimeoutError:
            return ""

    async def wait_for_bot_reply(self, *, timeout: float | None = None) -> ChatMessage:
        deadline = time.monotonic() + (timeout or self.cfg.command_timeout_seconds)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"No production bot reply for actor {self.actor.name}")
            message = await asyncio.wait_for(self.messages.get(), timeout=remaining)
            if self.cfg.production_bot_login and message.author_login.lower() != self.cfg.production_bot_login.lower():
                continue
            if self.cfg.production_bot_user_id and message.author_id != self.cfg.production_bot_user_id:
                continue
            return message


class ActorPool:
    def __init__(self, cfg: RunnerSettings):
        self.cfg = cfg
        self.clients = {
            actor.name: ActorClient(actor, cfg) for actor in cfg.actors() if actor.configured
        }

    @property
    def configured_names(self) -> list[str]:
        return sorted(self.clients)

    def require(self, *names: str) -> None:
        missing = [name for name in names if name not in self.clients]
        if missing:
            raise RuntimeError(f"Missing configured Twitch E2E actors: {', '.join(missing)}")

    async def start(self, *names: str) -> None:
        selected = [self.clients[name] for name in (names or tuple(self.clients))]
        await asyncio.gather(*(client.start_background() for client in selected))
        await asyncio.gather(
            *(
                asyncio.wait_for(client.ready.wait(), timeout=self.cfg.actor_start_timeout_seconds)
                for client in selected
            )
        )

    async def stop(self) -> None:
        await asyncio.gather(*(client.stop_background() for client in self.clients.values()))

    async def send_and_wait(self, actor_name: str, command: str) -> ChatMessage:
        client = self.clients[actor_name]
        source_request_id = await client.send_command(command)
        reply = await client.wait_for_bot_reply()
        return replace(reply, source_request_id=source_request_id)

    async def send_concurrent(self, commands: list[tuple[str, str]]) -> list[ChatMessage]:
        async def one(actor_name: str, command: str) -> ChatMessage:
            return await self.send_and_wait(actor_name, command)

        return list(await asyncio.gather(*(one(actor, command) for actor, command in commands)))
