from functools import cached_property

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

    DB_USER: str = "postgres"
    DB_PASSWORD: str = "password"
    DB_NAME: str = "fisher_db"
    DB_HOST: str = "postgres"
    DB_PORT: str = "5432"
    DATABASE_URL_OVERRIDE: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "DATABASE_URL_OVERRIDE"),
    )
    REDIS_URL: str = "redis://redis:6379/0"

    SECRET_KEY: str
    ENCRYPTION_KEY: str | None = None
    # Dedicated key for provider credentials.  It is intentionally separate
    # from SECRET_KEY/ENCRYPTION_KEY and is required for provider mutations.
    INTEGRATIONS_ENCRYPTION_KEY: str | None = None
    # Optional JSON object containing versioned previous keys, for example
    # {"1":"old-fernet-key","2":"current-fernet-key"}.  The current
    # version still comes from INTEGRATIONS_ENCRYPTION_KEY.
    INTEGRATIONS_ENCRYPTION_KEYS: str | None = None
    INTEGRATIONS_ENCRYPTION_KEY_VERSION: int = 1
    BOT_API_KEY: str
    DISCORD_BOT_API_KEY: str
    # Dedicated least-privilege credential for bot_gateway internal control APIs.
    # It is intentionally optional for read-only local deployments; requests
    # are rejected when it is not configured.
    TWITCH_BOT_SERVICE_KEY: str | None = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    TWITCH_CLIENT_ID: str
    TWITCH_CLIENT_SECRET: str
    TWITCH_OAUTH_REDIRECT_URIS: str = "http://localhost:5173/auth/callback"
    TWITCH_DISCORD_REDIRECT_URI: str = "http://localhost:8000/v1/auth/twitch/discord/callback"

    CORS_ORIGINS: str = "http://localhost:5173"
    RUN_BACKGROUND_WORKERS: bool = False
    STREAM_ELEMENTS_ECONOMY_ENABLED: bool = True
    LOG_LEVEL: str = "INFO"

    # Retention policy (days); 0 disables that category.
    RETENTION_RESOLVED_CAST_DAYS: int = 730
    RETENTION_REJECTED_CAST_DAYS: int = 60
    RETENTION_EXPIRED_IDEMPOTENCY_DAYS: int = 30
    RETENTION_AUDIT_LOG_DAYS: int = 365
    RETENTION_ECONOMY_OPERATIONS_DAYS: int = 365
    RETENTION_OUTBOX_EVENTS_DAYS: int = 90
    RETENTION_INVENTORY_USE_RECORDS_DAYS: int = 365

    # Fishing cast ledger rollout controls (plan Stage 8).
    FISHING_CAST_LEDGER_ENABLED: bool = True
    # Strict mode is on by default: a failed ledger write rolls back the cast
    # instead of silently continuing without a journal row (Gate E).
    FISHING_CAST_LEDGER_STRICT: bool = True

    @property
    def DATABASE_URL(self) -> str:
        if self.DATABASE_URL_OVERRIDE:
            return self.DATABASE_URL_OVERRIDE
        return (
            f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @cached_property
    def cors_origins(self) -> list[str]:
        return [value.strip() for value in self.CORS_ORIGINS.split(",") if value.strip()]

    @cached_property
    def twitch_oauth_redirect_uris(self) -> set[str]:
        return {
            value.strip()
            for value in self.TWITCH_OAUTH_REDIRECT_URIS.split(",")
            if value.strip()
        }

    @field_validator(
        "SECRET_KEY",
        "BOT_API_KEY",
        "DISCORD_BOT_API_KEY",
        "TWITCH_CLIENT_ID",
        "TWITCH_CLIENT_SECRET",
    )
    @classmethod
    def reject_empty_secrets(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized


settings = Settings()
