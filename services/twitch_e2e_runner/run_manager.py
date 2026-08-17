"""Redacted durable test-run history."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class RunManager:
    def __init__(self, path: str, *, deployment_version: str = "unknown", git_sha: str = "unknown"):
        self.path = path
        self.deployment_version = deployment_version
        self.git_sha = git_sha
        self._lock = asyncio.Lock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS synthetic_test_runs (
                    id TEXT PRIMARY KEY, suite TEXT NOT NULL, scenario TEXT NOT NULL,
                    channel_id TEXT, actor_id TEXT, secondary_actor_id TEXT,
                    started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
                    failure_stage TEXT, error_code TEXT, error_message TEXT,
                    source_twitch_message_id TEXT, fishing_cast_id TEXT,
                    economy_operation_id TEXT, checks_json TEXT NOT NULL,
                    deployment_version TEXT NOT NULL, git_sha TEXT NOT NULL
                )"""
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(synthetic_test_runs)")}
            if "git_sha" not in columns:
                db.execute(
                    "ALTER TABLE synthetic_test_runs ADD COLUMN git_sha TEXT NOT NULL "
                    "DEFAULT 'unknown'"
                )

    async def start(
        self,
        suite: str,
        scenario: str,
        channel_id: str,
        actor_id: str,
        secondary_actor_id: str | None = None,
    ) -> str:
        run_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            with sqlite3.connect(self.path) as db:
                db.execute(
                    "INSERT INTO synthetic_test_runs "
                    "(id,suite,scenario,channel_id,actor_id,secondary_actor_id,started_at,"
                    "status,checks_json,deployment_version,git_sha) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        suite,
                        scenario,
                        channel_id,
                        actor_id,
                        secondary_actor_id,
                        now,
                        "running",
                        "{}",
                        self.deployment_version,
                        self.git_sha,
                    ),
                )
        return run_id

    async def finish(self, run_id: str, result: dict[str, Any]) -> None:
        status = str(result.get("status", "failed"))
        error = result.get("error") or {}
        async with self._lock:
            with sqlite3.connect(self.path) as db:
                db.execute(
                    "UPDATE synthetic_test_runs SET finished_at=?, status=?, failure_stage=?, "
                    "error_code=?, error_message=?, source_twitch_message_id=?, fishing_cast_id=?, "
                    "economy_operation_id=?, checks_json=? WHERE id=?",
                    (
                        datetime.now(timezone.utc).isoformat(),
                        status,
                        error.get("stage"),
                        error.get("code"),
                        error.get("message"),
                        result.get("source_twitch_message_id"),
                        result.get("fishing_cast_id"),
                        result.get("economy_operation_id"),
                        json.dumps(result.get("checks", {}), ensure_ascii=False, default=str),
                        run_id,
                    ),
                )

    async def get(self, run_id: str) -> dict[str, Any] | None:
        async with self._lock:
            with sqlite3.connect(self.path) as db:
                db.row_factory = sqlite3.Row
                row = db.execute(
                    "SELECT * FROM synthetic_test_runs WHERE id=?", (run_id,)
                ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["checks"] = json.loads(result.pop("checks_json") or "{}")
        return result


def redact_result(result: dict[str, Any]) -> dict[str, Any]:
    """Remove token-shaped keys before persistence or API responses."""

    secret_keys = {"access_token", "refresh_token", "client_secret", "authorization", "jwt"}

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if key.lower() in secret_keys else clean(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(result)
