"""Environment-only configuration for the Twitch E2E runner."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ActorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: Literal["owner", "editor", "viewer"]
    user_id: str = ""
    login: str = ""
    access_token: str = ""
    refresh_token: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.user_id and self.login and self.access_token)

    def safe_summary(self) -> dict[str, str | bool]:
        return {
            "name": self.name,
            "role": self.role,
            "login": self.login,
            "configured": self.configured,
        }


class RunnerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

    enabled: bool = Field(default=False, validation_alias="TWITCH_E2E_ENABLED")
    mode: Literal["real", "stub"] = Field(default="real", validation_alias="TWITCH_E2E_MODE")
    transport: Literal["real", "disabled"] = Field(
        default="disabled", validation_alias="TWITCH_E2E_TRANSPORT"
    )
    channel: str = Field(default="", validation_alias="TWITCH_E2E_CHANNEL")
    channel_id: str = Field(default="", validation_alias="TWITCH_E2E_CHANNEL_ID")
    production_bot_login: str = Field(default="", validation_alias="TWITCH_E2E_BOT_LOGIN")
    production_bot_user_id: str = Field(default="", validation_alias="TWITCH_E2E_BOT_USER_ID")
    twitch_client_id: str = Field(default="", validation_alias="TWITCH_E2E_CLIENT_ID")
    twitch_client_secret: str = Field(default="", validation_alias="TWITCH_E2E_CLIENT_SECRET")
    engine_url: str = Field(
        default="http://game_engine:8000", validation_alias="TWITCH_E2E_ENGINE_URL"
    )
    engine_api_key: str = Field(default="", validation_alias="TWITCH_E2E_ENGINE_API_KEY")
    stub_url: str = Field(
        default="http://streamelements_stub:8080", validation_alias="TWITCH_E2E_STUB_URL"
    )
    stub_control_key: str = Field(default="", validation_alias="TWITCH_E2E_STUB_CONTROL_KEY")
    runner_api_key: str = Field(default="", validation_alias="TWITCH_E2E_RUNNER_API_KEY")
    result_db_path: str = Field(
        default_factory=lambda: str(Path(tempfile.gettempdir()) / "twitch_e2e_runs.sqlite3"),
        validation_alias="TWITCH_E2E_RESULT_DB",
    )
    command_timeout_seconds: float = Field(
        default=20.0, validation_alias="TWITCH_E2E_COMMAND_TIMEOUT"
    )
    actor_start_timeout_seconds: float = Field(
        default=30.0, validation_alias="TWITCH_E2E_ACTOR_START_TIMEOUT"
    )
    max_concurrency: int = Field(
        default=8, ge=1, le=32, validation_alias="TWITCH_E2E_MAX_CONCURRENCY"
    )
    deployment_version: str = Field(
        default="unknown", validation_alias="TWITCH_E2E_DEPLOYMENT_VERSION"
    )
    git_sha: str = Field(default="unknown", validation_alias="GIT_SHA")

    def actors(self) -> list[ActorConfig]:
        common_id = self.twitch_client_id
        common_secret = self.twitch_client_secret
        return [
            _actor_from_env("owner", "owner", common_id, common_secret),
            _actor_from_env("editor", "editor", common_id, common_secret),
            _actor_from_env("viewer1", "viewer", common_id, common_secret),
            _actor_from_env("viewer2", "viewer", common_id, common_secret),
        ]

    @property
    def transport_enabled(self) -> bool:
        """Whether scenarios may send real Twitch chat messages."""

        return self.transport == "real"


def _actor_from_env(name: str, role: str, client_id: str, client_secret: str) -> ActorConfig:
    # client credentials are intentionally read and discarded here: TwitchIO
    # receives only the token needed to open the actor session.
    del client_id, client_secret
    prefix = f"TWITCH_E2E_{name.upper()}_"
    import os

    return ActorConfig(
        name=name,
        role=role,  # type: ignore[arg-type]
        user_id=os.getenv(f"{prefix}USER_ID", "").strip(),
        login=os.getenv(f"{prefix}LOGIN", "").strip().lower(),
        access_token=os.getenv(f"{prefix}ACCESS_TOKEN", "").strip(),
        refresh_token=os.getenv(f"{prefix}REFRESH_TOKEN", "").strip(),
    )


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    owner_only: bool = False
    editor_allowed: bool = False


COMMAND_SURFACE: tuple[CommandSpec, ...] = (
    CommandSpec("fish"),
    CommandSpec("fishstats"),
    CommandSpec("fishtop"),
    CommandSpec("fishtravel"),
    CommandSpec("fishbag"),
    CommandSpec("fishtrash"),
    CommandSpec("fishequip"),
    CommandSpec("fishsell"),
    CommandSpec("fishbuy"),
    CommandSpec("fishrate"),
    CommandSpec("fishmods"),
    CommandSpec("fishmodadd", owner_only=True, editor_allowed=True),
    CommandSpec("fishmoddel", owner_only=True, editor_allowed=True),
    CommandSpec("fishcd"),
    CommandSpec("fishevent", owner_only=True, editor_allowed=True),
    CommandSpec("fisheconomy", owner_only=True, editor_allowed=True),
)


settings = RunnerSettings()
