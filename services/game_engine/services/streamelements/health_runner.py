"""Durable StreamElements credential/provider health reconciliation."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from core import metrics
from core.security import decrypt_integration_token
from infrastructure.database import SessionLocal
from infrastructure.models import ChannelIntegration
from infrastructure.redis_client import RedisClient
from infrastructure.se_client import (
    ProviderAuthenticationError,
    ProviderError,
    SEApiClient,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HealthProbeResult:
    status: str
    error_code: str | None
    http_status: int | None
    latency_ms: int


class ProviderIdentityMismatch(ProviderError):
    code = "STREAM_ELEMENTS_PROVIDER_IDENTITY_MISMATCH"


def classify_probe_error(error: Exception) -> tuple[str, str]:
    """Map provider/decryption failures to the stable health state contract."""

    if isinstance(error, ProviderIdentityMismatch):
        return "invalid", error.code
    if isinstance(error, ProviderAuthenticationError) or getattr(error, "status_code", None) in {
        401,
        403,
    }:
        return "invalid", "STREAM_ELEMENTS_INVALID_CREDENTIALS"
    if isinstance(error, ValueError):
        return "invalid", "STREAM_ELEMENTS_CREDENTIAL_DECRYPTION_FAILED"
    return "degraded", getattr(error, "code", "STREAM_ELEMENTS_PROVIDER_UNAVAILABLE")


def backoff_seconds(failures: int, *, rng: Callable[[float, float], float] = random.uniform) -> float:
    normalized = max(failures, 1)
    base = 1800 if normalized >= 5 else {1: 60, 2: 120, 3: 300, 4: 900}[normalized]
    return base * rng(0.9, 1.1)


def regular_interval_seconds(*, rng: Callable[[float, float], float] = random.uniform) -> float:
    return 1800 * rng(0.9, 1.1)


class StreamElementsHealthRunner:
    DUE_KEY = "fish:se:health:due"
    LOCK_PREFIX = "fish:se:health:lock:"
    HEARTBEAT_KEY = "fish:worker:se-health"
    CACHE_PREFIX = "fish:se:health:status:"
    LOCK_TTL = 60
    HEARTBEAT_TTL = 30
    CACHE_TTL = 600

    def __init__(
        self,
        *,
        poll_interval_seconds: float = 5.0,
        scheduler_reconcile_seconds: float = 300.0,
        db_factory=SessionLocal,
        redis_client=None,
        se_client: SEApiClient | None = None,
        worker_id: str | None = None,
        random_fn: Callable[[float, float], float] = random.uniform,
    ):
        self.poll_interval_seconds = max(poll_interval_seconds, 0.2)
        self.scheduler_reconcile_seconds = max(scheduler_reconcile_seconds, 1.0)
        self.db_factory = db_factory
        self.redis = redis_client or RedisClient.get_client()
        self.se_client = se_client or SEApiClient()
        self.worker_id = worker_id or uuid.uuid4().hex
        self.random_fn = random_fn
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_scheduler_reconcile = 0.0
        self._last_successful_check_at: datetime | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._rebuild_scheduler()
        self._task = asyncio.create_task(self._run(), name="streamelements-health-runner")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
            self._task = None
        await self.se_client.close()

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("StreamElements health runner tick failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.poll_interval_seconds
                )
            except asyncio.TimeoutError:
                pass

    async def run_once(self) -> int:
        now = time.time()
        self._heartbeat()
        if now - self._last_scheduler_reconcile >= self.scheduler_reconcile_seconds:
            self._reconcile_scheduler()
            self._last_scheduler_reconcile = now
        due = self.redis.zrangebyscore(self.DUE_KEY, "-inf", now, start=0, num=100)
        processed = 0
        for integration_id in due:
            if not self._acquire_lock(str(integration_id)):
                continue
            try:
                await self._check_one(str(integration_id))
                processed += 1
            finally:
                self._release_lock(str(integration_id))
        self._heartbeat(due_queue_size=len(due))
        return processed

    def _rebuild_scheduler(self) -> None:
        db = self.db_factory()
        try:
            rows = (
                db.query(ChannelIntegration)
                .filter(ChannelIntegration.status != "disconnected")
                .all()
            )
            now = datetime.now(timezone.utc)
            changed = False
            for row in rows:
                if row.next_validation_at is None:
                    row.next_validation_at = now
                    changed = True
                self.redis.zadd(self.DUE_KEY, {str(row.id): row.next_validation_at.timestamp()})
            if changed:
                db.commit()
        finally:
            db.close()

    def _reconcile_scheduler(self) -> None:
        self._rebuild_scheduler()

    async def _check_one(self, integration_id: str) -> HealthProbeResult | None:
        db = self.db_factory()
        try:
            try:
                parsed_id = uuid.UUID(integration_id)
            except ValueError:
                self.redis.zrem(self.DUE_KEY, integration_id)
                return None
            integration = (
                db.query(ChannelIntegration)
                .filter(ChannelIntegration.id == parsed_id)
                .with_for_update()
                .first()
            )
            if not integration:
                self.redis.zrem(self.DUE_KEY, integration_id)
                return None
            if integration.status == "disconnected":
                integration.next_validation_at = None
                db.commit()
                self.redis.zrem(self.DUE_KEY, integration_id)
                self.redis.delete(f"{self.CACHE_PREFIX}{integration.channel_id}")
                return None

            started = time.perf_counter()
            try:
                token = decrypt_integration_token(
                    integration.credential_ciphertext,
                    key_version=integration.credential_key_version,
                )
                provider_channel_id = await self.se_client.get_channel_id(token)
                if provider_channel_id != integration.provider_channel_id:
                    raise ProviderIdentityMismatch("Provider channel identity changed")
            except Exception as error:
                result = self._failure_result(error, started)
                previous = integration.status
                self._apply_failure(integration, result)
                db.commit()
                self._schedule(integration)
                self._write_cache(integration, result.latency_ms)
                self._log_transition(integration, previous, result)
                return result

            result = HealthProbeResult(
                "connected", None, 200, max(int((time.perf_counter() - started) * 1000), 0)
            )
            previous = integration.status
            self._apply_success(integration, result)
            db.commit()
            self._schedule(integration)
            self._last_successful_check_at = datetime.now(timezone.utc)
            self._write_cache(integration, result.latency_ms)
            self._log_transition(integration, previous, result)
            return result
        finally:
            db.close()

    def _failure_result(self, error: Exception, started: float) -> HealthProbeResult:
        status, code = classify_probe_error(error)
        return HealthProbeResult(
            status,
            code,
            getattr(error, "status_code", None),
            max(int((time.perf_counter() - started) * 1000), 0),
        )

    def _apply_success(self, integration: ChannelIntegration, result: HealthProbeResult) -> None:
        now = datetime.now(timezone.utc)
        integration.status = "connected"
        integration.last_check_at = now
        integration.last_success_at = now
        integration.last_validated_at = now
        integration.last_error_at = None
        integration.last_error_code = None
        integration.consecutive_failures = 0
        integration.validation_latency_ms = result.latency_ms
        integration.next_validation_at = now + timedelta(
            seconds=regular_interval_seconds(rng=self.random_fn)
        )

    def _apply_failure(self, integration: ChannelIntegration, result: HealthProbeResult) -> None:
        now = datetime.now(timezone.utc)
        integration.status = result.status
        integration.last_check_at = now
        integration.last_error_at = now
        integration.last_error_code = result.error_code
        integration.consecutive_failures += 1
        integration.validation_latency_ms = result.latency_ms
        if result.status == "invalid":
            delay = 6 * 3600
        else:
            delay = backoff_seconds(integration.consecutive_failures, rng=self.random_fn)
        integration.next_validation_at = now + timedelta(seconds=delay)

    def _schedule(self, integration: ChannelIntegration) -> None:
        if integration.next_validation_at is None:
            self.redis.zrem(self.DUE_KEY, str(integration.id))
        else:
            self.redis.zadd(self.DUE_KEY, {str(integration.id): integration.next_validation_at.timestamp()})

    def _write_cache(self, integration: ChannelIntegration, latency_ms: int) -> None:
        self.redis.setex(
            f"{self.CACHE_PREFIX}{integration.channel_id}",
            self.CACHE_TTL,
            json.dumps(
                {
                    "status": integration.status,
                    "last_check_at": integration.last_check_at.isoformat()
                    if integration.last_check_at
                    else None,
                    "last_success_at": integration.last_success_at.isoformat()
                    if integration.last_success_at
                    else None,
                    "next_check_at": integration.next_validation_at.isoformat()
                    if integration.next_validation_at
                    else None,
                    "consecutive_failures": integration.consecutive_failures,
                    "latency_ms": latency_ms,
                }
            ),
        )

    def _heartbeat(self, *, due_queue_size: int = 0) -> None:
        now = datetime.now(timezone.utc)
        self.redis.setex(
            self.HEARTBEAT_KEY,
            self.HEARTBEAT_TTL,
            json.dumps(
                {
                    "worker_id": self.worker_id,
                    "last_tick_at": now.isoformat(),
                    "last_successful_check_at": self._last_successful_check_at.isoformat()
                    if self._last_successful_check_at
                    else None,
                    "due_queue_size": due_queue_size,
                }
            ),
        )

    def _acquire_lock(self, integration_id: str) -> bool:
        return bool(
            self.redis.set(
                f"{self.LOCK_PREFIX}{integration_id}", self.worker_id, nx=True, ex=self.LOCK_TTL
            )
        )

    def _release_lock(self, integration_id: str) -> None:
        self.redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            f"{self.LOCK_PREFIX}{integration_id}",
            self.worker_id,
        )

    @staticmethod
    def _log_transition(
        integration: ChannelIntegration,
        previous: str,
        result: HealthProbeResult,
    ) -> None:
        metrics.inc("streamelements_health_checks_total", {"result": result.status})
        metrics.set_gauge("streamelements_health_check_duration_seconds", result.latency_ms / 1000)
        if previous != result.status:
            metrics.inc(
                "streamelements_health_transitions_total",
                {"from": previous, "to": result.status},
            )
        logger.info(
            "StreamElements health check completed",
            extra={
                "action": "streamelements_health_check",
                "integration_id": str(integration.id),
                "channel_id": integration.channel_id,
                "previous_status": previous,
                "new_status": result.status,
                "http_status": result.http_status,
                "latency_ms": result.latency_ms,
            },
        )
