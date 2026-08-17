"""TwitchIO actor sessions and response correlation."""

from __future__ import annotations

import asyncio
import logging
import re
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
_DEFAULT_IRC_RETRY_SECONDS = 1.0
_IRC_RETRY_PATTERN = re.compile(r"try again in\s+(?P<seconds>[0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _irc_retry_delay(error: Exception, attempt: int) -> float:
    """Return a bounded delay for Twitch IRC rate-limit responses.

    TwitchIO includes the server-provided retry interval in
    ``IRCCooldownError``.  Parsing the human-readable text keeps the runner
    compatible with TwitchIO 2.x without importing a private exception type.
    A small fallback backoff handles versions that omit that text.
    """

    match = _IRC_RETRY_PATTERN.search(str(error))
    if match:
        return max(float(match.group("seconds")) + 0.25, _DEFAULT_IRC_RETRY_SECONDS)
    return _DEFAULT_IRC_RETRY_SECONDS * (attempt + 1)


def _wire_command(command: str, duplicate_count: int) -> str:
    """Make repeated Twitch messages distinct without changing parsed args."""

    if duplicate_count <= 0:
        return command
    if command.strip().lower() == "!fish":
        return f'!fish "e2e-duplicate-{duplicate_count}"'
    # Twitch normalizes runs of ASCII spaces while de-duplicating chat
    # messages.  NBSP is still whitespace to TwitchIO's parser, but remains a
    # distinct IRC payload so two identical race commands are both delivered.
    nbsp_separator = "\u00a0" * (duplicate_count + 1)
    head, delimiter, tail = command.partition(" ")
    if not delimiter:
        return f"{head}{nbsp_separator}"
    return f"{head}{nbsp_separator}{tail.lstrip()}"


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
        self._send_lock = asyncio.Lock()
        self._last_send_at = 0.0
        self._last_command = ""
        self._duplicate_command_count = 0

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
        if self._task is not None and self._task.done():
            error = self._task.exception()
            self._task = None
            self.ready.clear()
            if error is not None:
                logger.warning(
                    "E2E actor session will be restarted role=%s login=%s previous_error=%s",
                    self.actor.role,
                    self.actor.login,
                    type(error).__name__,
                )
        if self._task is None:
            self._task = asyncio.create_task(self.start())

    async def wait_ready(self, timeout: float) -> None:
        """Wait for readiness while surfacing a failed connection immediately."""

        deadline = time.monotonic() + timeout
        while not self.ready.is_set():
            if self._task is not None and self._task.done():
                error = self._task.exception()
                if error is not None:
                    raise RuntimeError(
                        f"Actor {self.actor.name} failed to connect: {type(error).__name__}"
                    ) from error
                raise RuntimeError(f"Actor {self.actor.name} session stopped before ready")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Actor {self.actor.name} did not become ready within {timeout:.1f}s"
                )
            await asyncio.sleep(min(0.1, remaining))

    async def stop_background(self) -> None:
        if self._task is not None:
            await self.close()
            try:
                await self._task
            except Exception:
                logger.debug("E2E actor session stopped", exc_info=True)
            self._task = None

    async def send_command(self, command: str) -> str:
        async with self._send_lock:
            deadline = time.monotonic() + self.cfg.command_timeout_seconds
            channel_name = self.cfg.channel.lstrip("#").lower()
            while (
                channel_name not in getattr(self._connection, "_cache", {})
                and time.monotonic() < deadline
            ):
                await asyncio.sleep(0.1)
            if channel_name not in getattr(self._connection, "_cache", {}):
                raise RuntimeError(f"Actor {self.actor.name} is not joined to the test channel")

            elapsed = time.monotonic() - self._last_send_at
            if elapsed < self.cfg.send_interval_seconds:
                await asyncio.sleep(self.cfg.send_interval_seconds - elapsed)

            if command == self._last_command:
                self._duplicate_command_count += 1
            else:
                self._last_command = command
                self._duplicate_command_count = 0
            wire_command = _wire_command(command, self._duplicate_command_count)

            for attempt in range(self.cfg.irc_retry_limit + 1):
                try:
                    sent = await self._channel().send(wire_command)
                    self._last_send_at = time.monotonic()
                    break
                except Exception as error:
                    if (
                        type(error).__name__ != "IRCCooldownError"
                        or attempt >= self.cfg.irc_retry_limit
                    ):
                        raise
                    delay = _irc_retry_delay(error, attempt)
                    logger.info(
                        "Twitch IRC cooldown actor=%s retry=%s delay=%.2fs",
                        self.actor.name,
                        attempt + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
            else:  # pragma: no cover - loop either sends or raises
                raise RuntimeError("Twitch command send retry loop ended unexpectedly")

            message_id = _text(getattr(sent, "id", None) if sent is not None else None)
            if message_id:
                return message_id
            try:
                echo_deadline = time.monotonic() + self.cfg.echo_timeout_seconds
                while True:
                    remaining = echo_deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    echo = await asyncio.wait_for(
                        self.echoes.get(), timeout=remaining
                    )
                    if echo.text == wire_command:
                        return echo.message_id
            except asyncio.TimeoutError:
                logger.warning(
                    "Timed out waiting for Twitch echo actor=%s command=%s",
                    self.actor.name,
                    command,
                )
                return ""

    async def wait_for_bot_reply(self, *, timeout: float | None = None) -> ChatMessage:
        deadline = time.monotonic() + (timeout or self.cfg.command_timeout_seconds)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"No production bot reply for actor {self.actor.name}")
            try:
                message = await asyncio.wait_for(self.messages.get(), timeout=remaining)
            except asyncio.TimeoutError as error:
                raise TimeoutError(
                    f"No production bot reply for actor {self.actor.name}"
                ) from error
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
        self._send_lock = asyncio.Lock()
        self._last_send_at = 0.0

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
                client.wait_ready(self.cfg.actor_start_timeout_seconds)
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
        source_request_id = await self._send_paced(client, command)
        reply = await client.wait_for_bot_reply()
        return replace(reply, source_request_id=source_request_id, sent_at=sent_at)

    async def _wait_for_replies(
        self, clients: list[ActorClient], count: int
    ) -> list[ChatMessage]:
        """Collect replies from all actor queues and deduplicate Twitch broadcasts."""

        deadline = time.monotonic() + self.cfg.command_timeout_seconds
        replies: list[ChatMessage] = []
        seen: set[tuple[str, str, str]] = set()
        while len(replies) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Received {len(replies)} of {count} production bot replies"
                )
            tasks = {
                asyncio.create_task(client.wait_for_bot_reply(timeout=remaining)): client
                for client in clients
            }
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                try:
                    message = task.result()
                except TimeoutError as error:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"Received {len(replies)} of {count} production bot replies"
                        ) from error
                    continue
                key = (
                    message.message_id,
                    message.author_login,
                    message.text,
                )
                if key in seen:
                    continue
                seen.add(key)
                replies.append(message)
                if len(replies) >= count:
                    break
        return replies

    async def _send_paced(self, client: ActorClient, command: str) -> str:
        """Rate-limit all test actors against the production bot's IRC budget."""

        async with self._send_lock:
            elapsed = time.monotonic() - self._last_send_at
            if elapsed < self.cfg.send_interval_seconds:
                await asyncio.sleep(self.cfg.send_interval_seconds - elapsed)
            source_request_id = await client.send_command(command)
            self._last_send_at = time.monotonic()
            return source_request_id

    async def send_concurrent(self, commands: list[tuple[str, str]]) -> list[ChatMessage]:
        await self.start(*(actor for actor, _ in commands))
        for client in self.clients.values():
            self._drain_messages(client)

        async def send(index: int, actor: str, command: str) -> tuple[str, float]:
            # Twitch IRC can drop one of two PRIVMSG frames written at the
            # exact same instant from independent sessions.  A tiny stagger
            # keeps the messages concurrent at the backend while allowing
            # Twitch to process each actor's frame reliably.
            if index:
                await asyncio.sleep(index * _CONCURRENT_SEND_STAGGER_SECONDS)
            sent_at = time.time()
            source_request_id = await self._send_paced(self.clients[actor], command)
            return source_request_id, sent_at

        send_results = await asyncio.gather(
            *(send(index, actor, command) for index, (actor, command) in enumerate(commands))
        )
        source_request_ids = [result[0] for result in send_results]
        sent_at = [result[1] for result in send_results]
        # A bot response may arrive only on the originating actor session or
        # on every joined session, depending on Twitch's delivery path. Read
        # all participating queues and deduplicate broadcast message IDs.
        participating_clients = list(
            dict.fromkeys(self.clients[actor] for actor, _ in commands)
        )
        replies = await self._wait_for_replies(participating_clients, len(commands))
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
