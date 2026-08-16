"""Durable Twitch channel membership reconciler.

The game engine owns desired membership.  This component only translates that
state into TwitchIO join/part calls and deliberately keeps the current joins
when the control-plane is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from api_client import EngineApiClient
from config import BotConfig
from core_metrics import inc, set_gauge

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DesiredChannel:
    twitch_id: str
    login: str


class TwitchChannelReconciler:
    def __init__(self, bot: Any, api_client: EngineApiClient, config: BotConfig):
        self.bot = bot
        self.api_client = api_client
        self.config = config
        self._joined: dict[str, str] = {
            f"bootstrap:{login.casefold()}": login.casefold()
            for login in config.bootstrap_channels
        }
        self._last_desired: dict[str, DesiredChannel] | None = None
        self._last_reconcile_error: str | None = None
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._force_rejoin = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            # event_ready is also dispatched after a Twitch websocket
            # reconnect. Wake the existing loop so it re-applies joins to the
            # fresh IRC session instead of waiting for the normal interval.
            # TwitchIO may retain stale connected_channels across reconnects,
            # so the next reconciliation must issue a real JOIN command.
            self._force_rejoin = True
            self._wake_event.set()
            return
        self._stop_event.clear()
        self._wake_event.clear()
        await self.reconcile_once()
        self._task = asyncio.create_task(self._run(), name="twitch-channel-reconciler")

    async def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._task:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._wake_event.wait(), timeout=self.config.channel_reconcile_seconds
                )
            except asyncio.TimeoutError:
                pass
            else:
                self._wake_event.clear()
            if not self._stop_event.is_set():
                await self.reconcile_once()

    async def reconcile_once(self) -> bool:
        started = asyncio.get_running_loop().time()
        try:
            payload = await self.api_client.desired_twitch_channels()
            desired = self._parse_desired(payload)
            self._last_desired = desired
        except Exception as error:  # control-plane failures are fail-safe
            inc("twitch_bot_reconcile_failures_total")
            self._last_reconcile_error = "control_plane_unavailable"
            logger.warning(
                "Twitch membership control-plane unavailable",
                extra={"error": type(error).__name__},
            )
            # Never interpret an unavailable engine as an empty desired set.
            # Bootstrap channels are a transitional startup fallback only.
            if self._last_desired is None and self.config.bootstrap_channels:
                fallback = {
                    f"bootstrap:{login.casefold()}": DesiredChannel(
                        f"bootstrap:{login.casefold()}", login.casefold()
                    )
                    for login in self.config.bootstrap_channels
                }
                try:
                    await self._apply(fallback)
                except Exception:
                    await self._report_status(None)
            else:
                await self._report_status(None)
            return False

        try:
            await self._apply(desired, force_rejoin=self._force_rejoin)
            self._force_rejoin = False
            self._last_reconcile_error = None
            inc("twitch_bot_reconcile_runs_total")
            return True
        except Exception as error:
            inc("twitch_bot_reconcile_failures_total")
            self._last_reconcile_error = type(error).__name__
            logger.warning(
                "Twitch membership reconciliation failed",
                extra={"error": type(error).__name__},
            )
            await self._report_status(desired)
            return False
        finally:
            set_gauge(
                "twitch_bot_reconcile_duration_seconds",
                asyncio.get_running_loop().time() - started,
            )

    async def _apply(
        self, desired: dict[str, DesiredChannel], *, force_rejoin: bool = False
    ) -> None:
        actual_logins = self._connected_logins()
        # A renamed login retains its stable Twitch identity when the runtime
        # already reports that login as joined.
        for twitch_id, item in desired.items():
            if force_rejoin:
                await self._join_channel(item)
                self._joined[twitch_id] = item.login
                continue
            if twitch_id in self._joined:
                self._joined[twitch_id] = item.login
                if item.login not in actual_logins:
                    await self._join_channel(item)
                continue
            matching_id = next(
                (known_id for known_id, login in self._joined.items() if login == item.login),
                None,
            )
            if matching_id is not None:
                self._joined[twitch_id] = self._joined.pop(matching_id)
                if item.login not in actual_logins:
                    # A bootstrap entry is only bookkeeping when database
                    # membership is enabled; it does not prove that the
                    # current IRC session has actually joined the channel.
                    await self._join_channel(item)
                continue
            if item.login in actual_logins:
                # TwitchIO may already be joined after a reconnect or an
                # externally-triggered join. Track the stable identity without
                # issuing a duplicate runtime join.
                self._joined[twitch_id] = item.login
                continue
            await self._join_channel(item)
            self._joined[twitch_id] = item.login

        desired_logins = {item.login for item in desired.values()}
        stale_logins = (set(self._joined.values()) | actual_logins) - desired_logins
        for login in stale_logins:
            stale_ids = [
                twitch_id for twitch_id, known_login in self._joined.items() if known_login == login
            ]
            if not stale_ids and login not in actual_logins:
                continue
            # Bootstrap-only identities are also removed once the database has
            # successfully returned a desired set.
            inc("twitch_bot_part_attempts_total")
            started = asyncio.get_running_loop().time()
            try:
                await self.bot.part_channels([login])
            except Exception:
                inc("twitch_bot_part_failures_total")
                raise
            for twitch_id in stale_ids:
                self._joined.pop(twitch_id, None)
            logger.info(
                "Twitch channel parted",
                extra={
                    "action": "twitch_channel_part",
                    "login": login,
                    "result": "success",
                    "latency_ms": int(
                        (asyncio.get_running_loop().time() - started) * 1000
                    ),
                },
            )

        set_gauge("twitch_bot_desired_channels", len(desired))
        set_gauge("twitch_bot_joined_channels", len(self._joined))
        await self._report_status(desired)

    async def _join_channel(self, item: DesiredChannel) -> None:
        inc("twitch_bot_join_attempts_total")
        started = asyncio.get_running_loop().time()
        try:
            await self.bot.join_channels([item.login])
        except Exception:
            inc("twitch_bot_join_failures_total")
            raise
        logger.info(
            "Twitch channel joined",
            extra={
                "action": "twitch_channel_join",
                "twitch_id": item.twitch_id,
                "login": item.login,
                "result": "success",
                "latency_ms": int((asyncio.get_running_loop().time() - started) * 1000),
            },
        )

    def _parse_desired(self, payload: dict[str, Any]) -> dict[str, DesiredChannel]:
        result: dict[str, DesiredChannel] = {}
        for item in payload.get("channels", []):
            twitch_id = str(item.get("twitch_id") or "").strip()
            login = str(item.get("login") or "").strip().casefold()
            if twitch_id and login:
                result[twitch_id] = DesiredChannel(twitch_id, login)
        return result

    def _connected_logins(self) -> set[str]:
        connected = getattr(self.bot, "connected_channels", ()) or ()
        if isinstance(connected, dict):
            connected = connected.keys()
        values: set[str] = set()
        for item in connected:
            login = getattr(item, "name", item)
            values.add(str(login).lstrip("#").casefold())
        return values

    async def _report_status(self, desired: dict[str, DesiredChannel] | None) -> None:
        desired = desired or self._last_desired or {}
        actual = self._connected_logins()
        channels = []
        for twitch_id, item in desired.items():
            channels.append(
                {
                    "twitch_id": twitch_id,
                    "login": item.login,
                    "desired": "joined",
                    "actual": (
                        "joined"
                        if item.login in actual
                        else "joining" if twitch_id in self._joined else "unknown"
                    ),
                    "last_error": self._last_reconcile_error,
                }
            )
        try:
            await self.api_client.report_twitch_status(
                {
                    "instance_id": self.config.bot_instance_id,
                    "reported_at": datetime.now(timezone.utc).isoformat(),
                    "channels": channels,
                }
            )
        except Exception as error:
            logger.warning(
                "Unable to report Twitch membership status",
                extra={"error": type(error).__name__},
            )
