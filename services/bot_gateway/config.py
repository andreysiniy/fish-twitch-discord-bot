import os
import socket
from dataclasses import dataclass
from typing import List


@dataclass
class BotConfig:
    twitch_token: str
    twitch_client_id: str
    twitch_client_secret: str
    bot_nick: str
    bootstrap_channels: List[str]
    engine_url: str
    service_api_key: str
    channel_source: str = "database"
    channel_reconcile_seconds: float = 10.0
    bot_instance_id: str = ""
    command_prefix: str = "!"

    @property
    def initial_channels(self) -> List[str]:
        """Compatibility alias for integrations still reading the old name."""
        return self.bootstrap_channels

    @classmethod
    def from_env(cls) -> "BotConfig":
        channels_raw = os.getenv("BOOTSTRAP_CHANNELS") or os.getenv("INITIAL_CHANNELS", "")
        channels = [channel.strip() for channel in channels_raw.split(",") if channel.strip()]
        source = os.getenv("TWITCH_CHANNEL_SOURCE", "database").strip().lower()
        if source not in {"database", "bootstrap"}:
            raise ValueError("TWITCH_CHANNEL_SOURCE must be database or bootstrap")
        try:
            reconcile_seconds = max(float(os.getenv("TWITCH_CHANNEL_RECONCILE_SECONDS", "10")), 1.0)
        except ValueError as error:
            raise ValueError("TWITCH_CHANNEL_RECONCILE_SECONDS must be a number") from error

        return cls(
            twitch_token=os.getenv("TWITCH_TOKEN", ""),
            twitch_client_id=os.getenv("TWITCH_CLIENT_ID", ""),
            twitch_client_secret=os.getenv("TWITCH_CLIENT_SECRET", ""),
            bot_nick=os.getenv("BOT_NICK", ""),
            bootstrap_channels=channels,
            engine_url=os.getenv("ENGINE_URL", "http://localhost:8000"),
            service_api_key=os.getenv("TWITCH_BOT_SERVICE_KEY", ""),
            channel_source=source,
            channel_reconcile_seconds=reconcile_seconds,
            bot_instance_id=os.getenv("BOT_INSTANCE_ID") or socket.gethostname(),
            command_prefix=os.getenv("COMMAND_PREFIX", "!"),
        )
