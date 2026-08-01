from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DiscordSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=True,
        env_ignore_empty=True,
    )

    DISCORD_BOT_TOKEN: str
    DISCORD_APPLICATION_ID: int
    DISCORD_PUBLIC_KEY: str = ""
    DISCORD_BOT_API_KEY: str
    ENGINE_URL: str = "http://game_engine:8000"
    REDIS_URL: str = "redis://redis:6379/0"
    ENVIRONMENT: str = "production"
    LOG_LEVEL: str = "INFO"
    DEFAULT_LOCALE: str = "en"
    COMMAND_SYNC_MODE: str = "global"
    DEV_GUILD_ID: int | None = None
    HTTP_TIMEOUT_SECONDS: float = 8.0
    WIZARD_SESSION_TTL_SECONDS: int = 900
    OAUTH_LINK_TTL_SECONDS: int = 600
    HEALTH_PORT: int = 8081

    @field_validator("DISCORD_BOT_TOKEN", "DISCORD_BOT_API_KEY")
    @classmethod
    def secrets_must_not_be_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized

    @field_validator("COMMAND_SYNC_MODE")
    @classmethod
    def validate_sync_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"global", "guild"}:
            raise ValueError("COMMAND_SYNC_MODE must be global or guild")
        return normalized


settings = DiscordSettings()
