import os
from dataclasses import dataclass
from typing import List


@dataclass
class BotConfig:
    twitch_token: str
    twitch_client_id: str
    twitch_client_secret: str
    bot_nick: str
    initial_channels: List[str]
    engine_url: str
    command_prefix: str = "!"

    @classmethod
    def from_env(cls) -> "BotConfig":
        channels_raw = os.getenv("INITIAL_CHANNELS", "")
        channels = [channel.strip() for channel in channels_raw.split(",") if channel.strip()]

        return cls(
            twitch_token=os.getenv("TWITCH_TOKEN", ""),
            twitch_client_id=os.getenv("TWITCH_CLIENT_ID", ""),
            twitch_client_secret=os.getenv("TWITCH_CLIENT_SECRET", ""),
            bot_nick=os.getenv("BOT_NICK", ""),
            initial_channels=channels,
            engine_url=os.getenv("ENGINE_URL", "http://localhost:8000"),
            command_prefix=os.getenv("COMMAND_PREFIX", "!")
        )
