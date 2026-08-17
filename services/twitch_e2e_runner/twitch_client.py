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
    from twitchio.channel import Channel
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

    class Channel:  # type: ignore[no-redef]
        def __init__(self, name: str, websocket: object):
            self.name = name
            self._ws = websocket

logger = logging.getLogger(__name__)
_CONCURRENT_SEND_STAGGER_SECONDS = 0.05


def _text(value: object) -> str:
    return "" if value is None else str(value)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    author_login: str
    author_id: str
    text: str
    message_id: str
    received_at: float
    source_request_id: str = ""
    sent_at: float = 0.0


class ActorClient(Client):
    def __init__(self, actor: ActorConfig, cfg: RunnerSettings):
        token = actor.access_token
        if token and not token.startswith("oauth:"):
            token = f"oauth:{token}"
        super().__init__(
            token=token or None,
            client_secret=cfg.twitch_client_secret or None,
        )
        self.actor = actor
        self.cfg = cfg
        self.ready = asyncio.Event()
        self.messages: asyncio.Queue[ChatMessage] = asyncio.Queue()
        self.echoes: asyncio.Queue[ChatMessage] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def event_ready(self) -> None:
        if self.cfg.channel:
            await self.join_channels([self.cfg.channel])
            await self._wait_for_channel_join()
        # Do not release the startup barrier until TwitchIO has accepted the
        # join request. ``get_channel`` can still be populated asynchronously,
        # so ``send_command`` also waits for the channel object below.
        self.ready.set()
        logger.info("E2E actor session ready role=%s login=%s", self.actor.role, self.actor.login)

    async def _wait_for_channel_join(self) -> None:
        channel_name = self.cfg.channel.lstrip("#").lower()
        deadline = time.monotonic() + self.cfg.actor_start_timeout_seconds
        while time.monotonic() < deadline:
            pending = getattr(self._connection, "_join_pending", {})
            cache = getattr(self._connection, "_cache", {})
            if channel_name not in pending and channel_name in cache:
                return
            await asyncio.sleep(0.1)
        raise TimeoutError(f"Actor {self.actor.name} did not join {channel_name}")

    def _channel(self) -> Channel:
        """Return a channel bound to this actor's websocket connection.

        TwitchIO's ``Client.get_channel`` uses a process-wide id cache.  With
        multiple actor clients that cache can return another actor's Channel,
        making a command authenticate as the wrong Twitch user.  Constructing
        the lightweight Channel value directly keeps each send on its own IRC
        connection.
        """

        return Channel(name=self.cfg.channel.lstrip("#").lower(), websocket=self._connection)

    async def event_message(self, message) -> None:  # TwitchIO callback signature
        author = getattr(message, "author", None)
        chat_message = ChatMessage(
            author_login=_text(getattr(author, "name", "")),
            author_id=_text(getattr(author, "id", "")),
            text=_text(getattr(message, "content", "")),
            message_id=_text(getattr(message, "id", "")),
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
        deadline = time.monotonic() + self.cfg.command_timeout_seconds
        channel_name = self.cfg.channel.lstrip("#").lower()
        while (
            channel_name not in getattr(self._connection, "_cache", {})
            and time.monotonic() < deadline
        ):
            await asyncio.sleep(0.1)
        if channel_name not in getattr(self._connection, "_cache", {}):
            raise RuntimeError(f"Actor {self.actor.name} is not joined to the test channel")
        sent = await self._channel().send(command)
        message_id = _text(getattr(sent, "id", None) if sent is not None else None)
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
            if (
                self.cfg.production_bot_login
                and message.author_login.lower() != self.cfg.production_bot_login.lower()
            ):
                continue
            if (
                self.cfg.production_bot_user_id
                and message.author_id
                and message.author_id != self.cfg.production_bot_user_id
            ):
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
        await self.start(actor_name)
        client = self.clients[actor_name]
        self._drain_messages(client)
        sent_at = time.time()
        source_request_id = await client.send_command(command)
        reply = await client.wait_for_bot_reply()
        return replace(reply, source_request_id=source_request_id, sent_at=sent_at)

    async def send_concurrent(self, commands: list[tuple[str, str]]) -> list[ChatMessage]:
        await self.start(*(actor for actor, _ in commands))
        for client in self.clients.values():
            self._drain_messages(client)

        sent_at = [time.time() for _ in commands]

        async def send(index: int, actor: str, command: str) -> str:
            # Twitch IRC can drop one of two PRIVMSG frames written at the
            # exact same instant from independent sessions.  A tiny stagger
            # keeps the messages concurrent at the backend while allowing
            # Twitch to process each actor's frame reliably.
            if index:
                await asyncio.sleep(index * _CONCURRENT_SEND_STAGGER_SECONDS)
            return await self.clients[actor].send_command(command)

        source_request_ids = await asyncio.gather(
            *(send(index, actor, command) for index, (actor, command) in enumerate(commands))
        )
        # Twitch broadcasts each bot response to every joined actor session.
        # Consume one central queue; otherwise two actors can both claim the
        # same response and evidence becomes associated with the wrong user.
        central_client = self.clients[commands[0][0]]
        replies = [
            await central_client.wait_for_bot_reply() for _ in range(len(commands))
        ]
        return [
            replace(reply, source_request_id=source_request_ids[index], sent_at=sent_at[index])
            for index, reply in enumerate(replies)
        ]

    @staticmethod
    def _drain_messages(client: ActorClient) -> None:
        while True:
            try:
                client.messages.get_nowait()
            except asyncio.QueueEmpty:
                return
