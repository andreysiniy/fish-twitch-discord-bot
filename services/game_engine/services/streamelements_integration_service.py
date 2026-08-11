"""Discord-facing StreamElements connection and economy settings use cases."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from api.discord_dependencies import DiscordServiceContext
from core.api_errors import ApiProblem
from core.permissions import ChannelPermission
from core.security import (
    decrypt_integration_token,
    encrypt_integration_token,
    integration_key_fingerprint,
)
from domain.schemas.discord_admin import EconomySettingsPatchRequest
from infrastructure.models import (
    ChannelEconomySettings,
    ChannelIntegration,
    EconomyOperation,
)
from infrastructure.se_client import (
    ProviderAuthenticationError,
    ProviderError,
    SEApiClient,
)
from services.discord_admin_service import DiscordAdminService


class StreamElementsIntegrationService:
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
                credential_key_version=1,
                credential_fingerprint=integration_key_fingerprint(),
                status="connected",
                last_validated_at=now,
            )
            self.db.add(integration)
        else:
            integration.provider_channel_id = provider_channel_id
            integration.credential_ciphertext = ciphertext
            integration.credential_key_version = 1
            integration.credential_fingerprint = integration_key_fingerprint()
            integration.status = "connected"
            integration.version += 1
            integration.last_validated_at = now
            integration.last_error_code = None
        self.db.flush()
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
        integration = self._integration(channel.id)
        token = self._decrypt(integration)
        try:
            provider_channel_id = await self.se_client.get_channel_id(token)
        except ProviderError as error:
            integration.status = (
                "invalid" if isinstance(error, ProviderAuthenticationError) else "error"
            )
            integration.last_error_code = error.code
            self.db.flush()
            raise ApiProblem(
                502, error.code, "StreamElements test failed", request_id=context.request_id
            ) from error
        if provider_channel_id != integration.provider_channel_id:
            integration.status = "invalid"
            integration.last_error_code = "STREAM_ELEMENTS_CHANNEL_MISMATCH"
            self.db.flush()
            raise ApiProblem(
                409,
                "STREAM_ELEMENTS_CHANNEL_MISMATCH",
                "Provider channel identity changed",
                request_id=context.request_id,
            )
        integration.status = "connected"
        integration.last_validated_at = datetime.now(timezone.utc)
        integration.last_error_code = None
        self.db.flush()
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
        integration = self._integration(channel.id)
        before = self._serialize(integration)
        integration.status = "disconnected"
        integration.version += 1
        integration.last_error_code = None
        self.db.flush()
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
        if data.pricing_mode == "single_rate":
            assert data.points_per_kg is not None
            row.buy_points_per_kg = data.points_per_kg
            row.sell_points_per_kg = data.points_per_kg
        else:
            row.buy_points_per_kg = data.buy_points_per_kg
            row.sell_points_per_kg = data.sell_points_per_kg
        row.pricing_mode = data.pricing_mode
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

    def _integration(self, channel_id: int) -> ChannelIntegration:
        row = (
            self.db.query(ChannelIntegration)
            .filter(
                ChannelIntegration.channel_id == channel_id,
                ChannelIntegration.provider == "streamelements",
            )
            .first()
        )
        if not row or row.status != "connected":
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
            "last_error_code": row.last_error_code,
            "version": row.version,
        }

    def _serialize_settings(self, row: ChannelEconomySettings) -> dict[str, Any]:
        return {
            "pricing_mode": row.pricing_mode,
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
