"""Discord-facing StreamElements connection and economy settings use cases."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from api.discord_dependencies import DiscordServiceContext
from core.api_errors import ApiProblem
from core.config import settings
from core.permissions import ChannelPermission
from core.security import (
    decrypt_integration_token,
    encrypt_integration_token,
    integration_key_fingerprint,
)
from domain.schemas.discord_admin import EconomySettingsPatchRequest
from infrastructure.after_commit import run_after_commit_callbacks, schedule_after_commit
from infrastructure.models import (
    ChannelEconomySettings,
    ChannelIntegration,
    EconomyOperation,
)
from infrastructure.redis_client import RedisClient
from redis.exceptions import RedisError
from infrastructure.se_client import (
    ProviderAuthenticationError,
    ProviderError,
    SEApiClient,
)
from services.discord_admin_service import DiscordAdminService
from services.streamelements.health_policy import backoff_seconds


class StreamElementsIntegrationService:
    HEALTH_DUE_KEY = "fish:se:health:due"
    HEALTH_CACHE_PREFIX = "fish:se:health:status:"
    def __init__(self, db, se_client: SEApiClient | None = None):
        self.db = db
        self.se_client = se_client or SEApiClient()
        self.admin = DiscordAdminService(db)

    async def connect(
        self, context: DiscordServiceContext, channel_twitch_id: str, jwt_token: str
    ) -> dict[str, Any]:
        channel, _ = self.admin._authorize(
            context, ChannelPermission.INTEGRATIONS_WRITE, channel_twitch_id, for_update=True
        )
        token = str(jwt_token or "").strip()
        if not token:
            raise ApiProblem(
                422, "VALIDATION_ERROR", "JWT token is required", request_id=context.request_id
            )
        try:
            provider_channel_id = await self.se_client.get_channel_id(token)
        except ProviderAuthenticationError as error:
            raise ApiProblem(
                400,
                "STREAM_ELEMENTS_INVALID_CREDENTIALS",
                "StreamElements rejected this token",
                request_id=context.request_id,
            ) from error
        except ProviderError as error:
            raise ApiProblem(
                502,
                error.code,
                "StreamElements channel validation failed",
                request_id=context.request_id,
            ) from error
        try:
            ciphertext = encrypt_integration_token(token)
        except ValueError as error:
            raise ApiProblem(
                503,
                "INTEGRATION_KEY_UNAVAILABLE",
                "Integration encryption key is not configured",
                request_id=context.request_id,
            ) from error

        integration = (
            self.db.query(ChannelIntegration)
            .filter(
                ChannelIntegration.channel_id == channel.id,
                ChannelIntegration.provider == "streamelements",
            )
            .with_for_update()
            .first()
        )
        before = self._serialize(integration) if integration else {"status": "disconnected"}
        now = datetime.now(timezone.utc)
        if integration is None:
            integration = ChannelIntegration(
                channel_id=channel.id,
                provider_channel_id=provider_channel_id,
                credential_ciphertext=ciphertext,
                credential_key_version=settings.INTEGRATIONS_ENCRYPTION_KEY_VERSION,
                credential_fingerprint=integration_key_fingerprint(),
                status="connected",
                last_validated_at=now,
                last_check_at=now,
                last_success_at=now,
                next_validation_at=now + timedelta(minutes=30),
                consecutive_failures=0,
            )
            self.db.add(integration)
        else:
            integration.provider_channel_id = provider_channel_id
            integration.credential_ciphertext = ciphertext
            integration.credential_key_version = settings.INTEGRATIONS_ENCRYPTION_KEY_VERSION
            integration.credential_fingerprint = integration_key_fingerprint()
            integration.status = "connected"
            integration.version += 1
            integration.last_validated_at = now
            integration.last_check_at = now
            integration.last_success_at = now
            integration.last_error_at = None
            integration.next_validation_at = now + timedelta(minutes=30)
            integration.consecutive_failures = 0
            integration.validation_latency_ms = None
            integration.last_error_code = None
        self.db.flush()
        self._schedule_health_after_commit(integration)
        after = self._serialize(integration)
        self.admin._audit(
            context,
            channel.twitch_id,
            "streamelements.rotate_credential"
            if before.get("status") == "connected"
            else "streamelements.connect",
            "channel_integration",
            str(integration.id),
            before,
            after,
        )
        return after

    def status(self, context: DiscordServiceContext, channel_twitch_id: str) -> dict[str, Any]:
        channel, _ = self.admin._authorize(
            context, ChannelPermission.CONFIG_READ, channel_twitch_id
        )
        integration = (
            self.db.query(ChannelIntegration)
            .filter(
                ChannelIntegration.channel_id == channel.id,
                ChannelIntegration.provider == "streamelements",
            )
            .first()
        )
        return self._serialize(integration)

    async def test(self, context: DiscordServiceContext, channel_twitch_id: str) -> dict[str, Any]:
        channel, _ = self.admin._authorize(
            context, ChannelPermission.INTEGRATIONS_WRITE, channel_twitch_id
        )
        integration = self._integration(channel.id, lock=True)
        try:
            token = self._decrypt(integration)
        except ApiProblem:
            now = datetime.now(timezone.utc)
            integration.status = "invalid"
            integration.last_check_at = now
            integration.last_error_at = now
            integration.last_error_code = "STREAM_ELEMENTS_CREDENTIAL_DECRYPTION_FAILED"
            integration.consecutive_failures += 1
            integration.next_validation_at = now + timedelta(hours=6)
            self.db.flush()
            self._schedule_health_after_commit(integration)
            self.db.commit()
            run_after_commit_callbacks(self.db)
            raise
        started = datetime.now(timezone.utc)
        try:
            provider_channel_id = await self.se_client.get_channel_id(token)
        except ProviderError as error:
            self._record_failure(integration, error)
            self.db.flush()
            self._schedule_health_after_commit(integration)
            self.db.commit()
            run_after_commit_callbacks(self.db)
            problem_status = 400 if integration.status == "invalid" else 502
            problem_code = (
                "STREAM_ELEMENTS_INVALID_CREDENTIALS"
                if integration.status == "invalid"
                else error.code
            )
            problem_message = (
                "StreamElements rejected the credential"
                if integration.status == "invalid"
                else "StreamElements test failed"
            )
            raise ApiProblem(
                problem_status,
                problem_code,
                problem_message,
                request_id=context.request_id,
            ) from error
        if provider_channel_id != integration.provider_channel_id:
            error = ProviderError("Provider channel identity changed", status_code=409)
            self._record_failure(
                integration,
                error,
                code="STREAM_ELEMENTS_PROVIDER_IDENTITY_MISMATCH",
                status="invalid",
            )
            self.db.flush()
            self._schedule_health_after_commit(integration)
            self.db.commit()
            run_after_commit_callbacks(self.db)
            raise ApiProblem(
                409,
                "STREAM_ELEMENTS_CHANNEL_MISMATCH",
                "Provider channel identity changed",
                request_id=context.request_id,
            )
        now = datetime.now(timezone.utc)
        integration.status = "connected"
        integration.last_check_at = now
        integration.last_success_at = now
        integration.last_validated_at = now
        integration.last_error_at = None
        integration.last_error_code = None
        integration.consecutive_failures = 0
        integration.validation_latency_ms = max(int((now - started).total_seconds() * 1000), 0)
        integration.next_validation_at = now + timedelta(minutes=30)
        self.db.flush()
        self._schedule_health_after_commit(integration)
        self.admin._audit(
            context,
            channel.twitch_id,
            "streamelements.test",
            "channel_integration",
            str(integration.id),
            {},
            self._serialize(integration),
        )
        return {
            "status": "healthy",
            "provider": "streamelements",
            "last_validated_at": integration.last_validated_at.isoformat(),
        }

    def disconnect(self, context: DiscordServiceContext, channel_twitch_id: str) -> dict[str, Any]:
        channel, _ = self.admin._authorize(
            context, ChannelPermission.INTEGRATIONS_WRITE, channel_twitch_id, for_update=True
        )
        integration = self._integration(channel.id, lock=True)
        before = self._serialize(integration)
        integration.status = "disconnected"
        integration.version += 1
        integration.last_error_code = None
        integration.next_validation_at = None
        self.db.flush()
        integration_id = str(integration.id)
        channel_id = channel.id
        schedule_after_commit(
            self.db,
            lambda: self._remove_health_schedule(integration_id, channel_id),
        )
        after = self._serialize(integration)
        self.admin._audit(
            context,
            channel.twitch_id,
            "streamelements.disconnect",
            "channel_integration",
            str(integration.id),
            before,
            after,
        )
        return after

    def settings(self, context: DiscordServiceContext, channel_twitch_id: str) -> dict[str, Any]:
        channel, _ = self.admin._authorize(
            context, ChannelPermission.CONFIG_READ, channel_twitch_id
        )
        row = self._settings(channel.id, create=True)
        self.db.flush()
        return self._serialize_settings(row)

    def patch_settings(
        self,
        context: DiscordServiceContext,
        channel_twitch_id: str,
        data: EconomySettingsPatchRequest,
    ) -> dict[str, Any]:
        channel, _ = self.admin._authorize(
            context, ChannelPermission.CONFIG_WRITE, channel_twitch_id, for_update=True
        )
        row = self._settings(channel.id, create=True)
        if row.version != data.expected_version:
            raise ApiProblem(
                409,
                "ECONOMY_RATE_CONFLICT",
                "Economy settings changed; reload and try again",
                request_id=context.request_id,
            )
        before = self._serialize_settings(row)
        if data.buy_points_per_kg is not None and data.sell_points_per_kg is not None:
            row.buy_points_per_kg = data.buy_points_per_kg
            row.sell_points_per_kg = data.sell_points_per_kg
        for field in (
            "buy_enabled",
            "sell_enabled",
            "enabled",
            "min_transaction_mass",
            "max_transaction_mass",
        ):
            value = getattr(data, field)
            if value is not None:
                setattr(row, field, value)
        if row.max_transaction_mass < row.min_transaction_mass:
            raise ApiProblem(
                422,
                "VALIDATION_ERROR",
                "Maximum transaction mass must not be below minimum",
                request_id=context.request_id,
            )
        row.version += 1
        self.db.flush()
        after = self._serialize_settings(row)
        self.admin._audit(
            context,
            channel.twitch_id,
            "streamelements.settings.update",
            "channel_economy_settings",
            str(row.id),
            before,
            after,
        )
        return after

    def operations(
        self, context: DiscordServiceContext, channel_twitch_id: str, limit: int = 25
    ) -> dict[str, Any]:
        channel, _ = self.admin._authorize(
            context, ChannelPermission.CONFIG_READ, channel_twitch_id
        )
        rows = (
            self.db.query(EconomyOperation)
            .filter(EconomyOperation.channel_id == channel.id)
            .order_by(EconomyOperation.requested_at.desc())
            .limit(min(max(limit, 1), 100))
            .all()
        )
        return {"items": [self._serialize_operation(row) for row in rows]}

    def _schedule_health_after_commit(self, integration: ChannelIntegration) -> None:
        if integration.next_validation_at is None:
            return
        integration_id = str(integration.id)
        due_at = integration.next_validation_at.timestamp()
        schedule_after_commit(
            self.db,
            lambda: self._enqueue_health_schedule(integration_id, due_at),
        )

    def _enqueue_health_schedule(self, integration_id: str, due_at: float) -> None:
        try:
            RedisClient.get_client().zadd(
                self.HEALTH_DUE_KEY,
                {integration_id: due_at},
            )
        except RedisError:
            # PostgreSQL remains the source of truth; the worker rebuilds the
            # operational queue after Redis recovers.
            pass

    def _remove_health_schedule(self, integration_id: str, channel_id: int) -> None:
        try:
            redis = RedisClient.get_client()
            redis.zrem(self.HEALTH_DUE_KEY, integration_id)
            redis.delete(f"{self.HEALTH_CACHE_PREFIX}{channel_id}")
        except RedisError:
            pass

    @staticmethod
    def _record_failure(
        integration: ChannelIntegration,
        error: ProviderError,
        *,
        code: str | None = None,
        status: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        integration.status = status or (
            "invalid"
            if isinstance(error, ProviderAuthenticationError)
            or getattr(error, "status_code", None) in {401, 403}
            else "degraded"
        )
        integration.last_check_at = now
        integration.last_error_at = now
        integration.last_error_code = code or error.code
        integration.consecutive_failures += 1
        delay = 6 * 3600 if integration.status == "invalid" else backoff_seconds(
            integration.consecutive_failures
        )
        integration.next_validation_at = now + timedelta(seconds=delay)

    def _integration(
        self, channel_id: int, *, lock: bool = False
    ) -> ChannelIntegration:
        query = self.db.query(ChannelIntegration).filter(
            ChannelIntegration.channel_id == channel_id,
            ChannelIntegration.provider == "streamelements",
        )
        if lock:
            query = query.with_for_update()
        row = query.first()
        if not row or row.status in {"invalid", "disconnected"}:
            raise ApiProblem(
                409, "STREAM_ELEMENTS_NOT_CONFIGURED", "StreamElements integration is not connected"
            )
        return row

    def _decrypt(self, integration: ChannelIntegration) -> str:
        try:
            return decrypt_integration_token(
                integration.credential_ciphertext, key_version=integration.credential_key_version
            )
        except ValueError as error:
            raise ApiProblem(
                503, "INTEGRATION_KEY_UNAVAILABLE", "Integration credential cannot be decrypted"
            ) from error

    def _settings(self, channel_id: int, *, create: bool) -> ChannelEconomySettings:
        row = (
            self.db.query(ChannelEconomySettings)
            .filter(ChannelEconomySettings.channel_id == channel_id)
            .first()
        )
        if row is None and create:
            row = ChannelEconomySettings(channel_id=channel_id)
            self.db.add(row)
            self.db.flush()
        if row is None:
            raise ApiProblem(
                404, "ECONOMY_SETTINGS_NOT_FOUND", "Economy settings are not configured"
            )
        return row

    def _serialize(self, row: ChannelIntegration | None) -> dict[str, Any]:
        if row is None:
            return {
                "provider": "streamelements",
                "status": "disconnected",
                "credential_configured": False,
                "version": 0,
            }
        return {
            "provider": row.provider,
            "status": row.status,
            "provider_channel_id": row.provider_channel_id,
            "credential_configured": bool(row.credential_ciphertext),
            "credential_fingerprint": row.credential_fingerprint,
            "last_validated_at": row.last_validated_at.isoformat()
            if row.last_validated_at
            else None,
            "last_check_at": row.last_check_at.isoformat() if row.last_check_at else None,
            "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
            "last_error_at": row.last_error_at.isoformat() if row.last_error_at else None,
            "next_validation_at": row.next_validation_at.isoformat()
            if row.next_validation_at
            else None,
            "consecutive_failures": row.consecutive_failures,
            "validation_latency_ms": row.validation_latency_ms,
            "last_error_code": row.last_error_code,
            "version": row.version,
        }

    def _serialize_settings(self, row: ChannelEconomySettings) -> dict[str, Any]:
        return {
            "buy_points_per_kg": str(row.buy_points_per_kg),
            "sell_points_per_kg": str(row.sell_points_per_kg),
            "buy_enabled": row.buy_enabled,
            "sell_enabled": row.sell_enabled,
            "enabled": row.enabled,
            "min_transaction_mass": str(row.min_transaction_mass),
            "max_transaction_mass": str(row.max_transaction_mass),
            "version": row.version,
        }

    def _serialize_operation(self, row: EconomyOperation) -> dict[str, Any]:
        return {
            "operation_id": str(row.id),
            "operation_type": row.operation_type,
            "state": row.state,
            "username": row.twitch_username,
            "mass_delta": str(row.mass_delta),
            "points_delta": str(row.points_delta),
            "points_calculated": str(row.points_calculated),
            "rate": str(row.rate_used_snapshot or ""),
            "provider_channel_id": row.provider_channel_id_snapshot,
            "provider_points_cap": row.provider_points_cap,
            "provider_balance_before": row.provider_balance_before,
            "provider_balance_after": row.provider_balance_after,
            "provider_points_headroom_before": row.provider_points_headroom_before,
            "provider_points_headroom_after": row.provider_points_headroom_after,
            "external_applied": row.external_applied,
            "attempts": row.attempts,
            "last_error": row.last_error,
            "error_code": row.error_code,
            "reconciliation_reason": row.reconciliation_reason,
            "requested_at": row.requested_at.isoformat() if row.requested_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }
