"""Authoritative StreamElements mass/points conversion service."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal
from functools import wraps
from typing import TypeVar
from uuid import uuid4

from core.config import settings as engine_settings
from core.messages import (
    MsgKey,
    format_large_number_mass,
    format_large_number_points,
    resolve_message,
)
from core.metrics import count_economy_provider_cap_rejection, count_economy_reconciliation
from core.security import decrypt_integration_token, decrypt_token
from domain.economy import (
    MASS_QUANTUM,
    EconomyDomainError,
    ParsedMassArgument,
    calculate_buy_points,
    calculate_sell_points,
    parse_mass_argument,
)
from domain.item_schema import ModifierScope, StatKey
from domain.logic.mass import apply_mass_mutation
from domain.schemas.fishing import FishResponse
from infrastructure.models import (
    Channel,
    ChannelEconomySettings,
    ChannelIntegration,
    EconomyOperation,
    EconomyOperationEvent,
    EconomyProviderAttempt,
    OutboxEvent,
    UserProgress,
)
from infrastructure.redis_client import RedisClient
from infrastructure.repositories.channel_repo import ChannelRepository
from infrastructure.repositories.user_repo import UserRepository
from infrastructure.se_client import (
    ProviderAmbiguousWriteError,
    ProviderAuthenticationError,
    ProviderConnectionNotSentError,
    ProviderError,
    ProviderRateLimitError,
    ProviderValidationError,
    SEApiClient,
)
from integrations.streamelements.constants import (
    STREAMELEMENTS_POINTS_MAX,
    max_buy_mass,
    max_sell_mass,
    provider_headroom,
    validate_credit,
    validate_debit,
    validate_provider_balance,
)
from services.player_modifier_service import PlayerModifierService

_BuyCallable = TypeVar("_BuyCallable", bound=Callable[..., Coroutine[object, object, FishResponse]])
_SellCallable = TypeVar(
    "_SellCallable", bound=Callable[..., Coroutine[object, object, FishResponse]]
)


def _serialize_buy_requests(func: _BuyCallable) -> _BuyCallable:
    """Serialize purchases per viewer before any provider balance is read."""

    @wraps(func)
    async def wrapped(self, twitch_id: str, channel_id: str, *args, **kwargs):
        with self._buy_request_lock(channel_id, twitch_id):
            return await func(self, twitch_id, channel_id, *args, **kwargs)

    return wrapped  # type: ignore[return-value]


def _serialize_sell_requests(func: _SellCallable) -> _SellCallable:
    """Serialize sales per viewer before the provider balance is read."""

    @wraps(func)
    async def wrapped(self, twitch_id: str, channel_id: str, *args, **kwargs):
        with self._sell_request_lock(channel_id, twitch_id):
            return await func(self, twitch_id, channel_id, *args, **kwargs)

    return wrapped  # type: ignore[return-value]


class EconomyService:
    EXTERNAL_OPERATION_LEASE_SECONDS = 60

    def __init__(
        self, user_repo: UserRepository, channel_repo: ChannelRepository, se_client: SEApiClient
    ):
        self.user_repo = user_repo
        self.channel_repo = channel_repo
        self.se_client = se_client
        self.db = user_repo.db
        self.modifier_service = PlayerModifierService(self.db)

    @_serialize_sell_requests
    async def sell_fish(
        self,
        twitch_id: str,
        channel_id: str,
        amount_str: str | None,
        idempotency_key: str,
        source_request_id: str | None = None,
    ) -> FishResponse:
        if not engine_settings.STREAM_ELEMENTS_ECONOMY_ENABLED:
            raise EconomyDomainError(
                "STREAM_ELEMENTS_NOT_CONFIGURED", "StreamElements economy is disabled."
            )
        self._require_key(idempotency_key)
        previous = self._get_operation(
            idempotency_key,
            operation_type="sell",
            raw_argument=amount_str,
        )
        if previous:
            return self._stored_response(previous)
        user, channel, integration, settings = self._load_context(twitch_id, channel_id, lock=True)
        if user is None:
            return self._message(channel, MsgKey.ERR_NO_PROFILE, username=twitch_id)
        if not settings.enabled or not settings.sell_enabled:
            return self._message(channel, MsgKey.SELL_MASS_DISABLED)
        current_mass = self._decimal(user.current_mass)
        if current_mass <= 0:
            return self._message(channel, MsgKey.SELL_MASS_EMPTY)
        parsed = parse_mass_argument(amount_str, allow_all=True)
        token = self._decrypt_integration(integration, channel)
        # End the read-only transaction before waiting on StreamElements.  A
        # provider timeout must not retain a PostgreSQL connection or a row
        # lock needed by the next chat command.
        self.db.commit()
        try:
            provider_balance = validate_provider_balance(
                await self.se_client.get_balance(
                    str(integration.provider_channel_id),
                    token,
                    (user.username or "").strip() or twitch_id,
                )
            )
        except ProviderError as error:
            raise EconomyDomainError(
                error.code, "StreamElements is temporarily unavailable."
            ) from error
        user = self._lock_user(user.id)
        current_mass = self._decimal(user.current_mass)
        if current_mass <= 0:
            return self._message(channel, MsgKey.SELL_MASS_EMPTY)
        mass = self._resolve_sell_mass(parsed, current_mass, settings, provider_balance)
        rate = Decimal(str(settings.sell_points_per_kg))
        points = calculate_sell_points(mass, rate)
        if points <= 0:
            raise EconomyDomainError(
                "ECONOMY_INVALID_MASS", "Mass is too small for a points payout."
            )
        try:
            resulting_balance = validate_credit(provider_balance, points)
        except EconomyDomainError:
            if parsed.mode != "exact":
                raise EconomyDomainError(
                    "ECONOMY_NO_SELLABLE_MASS",
                    "No mass can be sold within the StreamElements points limit.",
                )
            operation = self._create_operation(
                idempotency_key=idempotency_key,
                operation_type="sell",
                source="twitch",
                channel=channel,
                integration=integration,
                user=user,
                parsed=parsed,
                mass=mass,
                points=points,
                rate=rate,
                settings=settings,
                mass_before=current_mass,
                balance_before=provider_balance,
                source_request_id=source_request_id,
            )
            operation.state = "failed"
            operation.error_code = "STREAMELEMENTS_POINTS_CAP_EXCEEDED"
            operation.reconciliation_reason = "provider_cap"
            count_economy_provider_cap_rejection("sell")
            operation.provider_points_cap = STREAMELEMENTS_POINTS_MAX
            operation.provider_points_headroom_before = provider_headroom(provider_balance)
            self._append_event(
                operation,
                "provider_balance_read",
                "processing",
                "failed",
                {
                    "balance": provider_balance,
                    "headroom": operation.provider_points_headroom_before,
                    "cap": STREAMELEMENTS_POINTS_MAX,
                },
            )
            response = self._message(
                channel,
                MsgKey.ECONOMY_CAP_EXCEEDED,
                cap=format_large_number_points(STREAMELEMENTS_POINTS_MAX),
                operation_id=str(operation.id),
            )
            operation.response_payload = response.model_dump(mode="json")
            self._mark_outbox(operation, "dead_letter")
            self.db.commit()
            return response
        before_mass = current_mass
        apply_mass_mutation(user, -mass, track_total=False)
        operation = self._create_operation(
            idempotency_key=idempotency_key,
            operation_type="sell",
            source="twitch",
            channel=channel,
            integration=integration,
            user=user,
            parsed=parsed,
            mass=mass,
            points=points,
            rate=rate,
            settings=settings,
            mass_before=before_mass,
            balance_before=provider_balance,
            source_request_id=source_request_id,
        )
        operation.provider_points_cap = STREAMELEMENTS_POINTS_MAX
        operation.provider_points_headroom_before = provider_headroom(provider_balance)
        operation.provider_points_headroom_after = provider_headroom(resulting_balance)
        self._append_event(
            operation,
            "provider_balance_read",
            "processing",
            "processing",
            {
                "balance": provider_balance,
                "headroom": operation.provider_points_headroom_before,
                "cap": STREAMELEMENTS_POINTS_MAX,
            },
        )
        self._mark_outbox(operation, "processing")
        self.db.commit()
        return await self._execute_sell(operation, channel, integration, token, settings)

    @_serialize_buy_requests
    async def buy_fish(
        self,
        twitch_id: str,
        channel_id: str,
        amount_str: str | None,
        idempotency_key: str,
        source_request_id: str | None = None,
    ) -> FishResponse:
        if not engine_settings.STREAM_ELEMENTS_ECONOMY_ENABLED:
            raise EconomyDomainError(
                "STREAM_ELEMENTS_NOT_CONFIGURED", "StreamElements economy is disabled."
            )
        self._require_key(idempotency_key)
        previous = self._get_operation(
            idempotency_key,
            operation_type="buy",
            raw_argument=amount_str,
        )
        if previous:
            return self._stored_response(previous)
        user, channel, integration, settings = self._load_context(twitch_id, channel_id, lock=False)
        if user is None:
            return self._message(channel, MsgKey.ERR_NO_PROFILE, username=twitch_id)
        if not settings.enabled or not settings.buy_enabled:
            return self._message(channel, MsgKey.SELL_MASS_DISABLED)
        parsed = parse_mass_argument(amount_str, allow_all=True)
        token = self._decrypt_integration(integration, channel)
        username = (user.username or "").strip() or twitch_id
        # The Redis request lock serializes concurrent purchases for one viewer
        # without holding a PostgreSQL row lock across the provider call.
        try:
            balance = await self.se_client.get_balance(
                str(integration.provider_channel_id), token, username
            )
        except ProviderAuthenticationError as error:
            raise EconomyDomainError(
                "STREAM_ELEMENTS_INVALID_CREDENTIALS", "StreamElements credentials are invalid."
            ) from error
        except ProviderError as error:
            raise EconomyDomainError(
                error.code, "StreamElements is temporarily unavailable."
            ) from error
        balance = validate_provider_balance(balance)
        rate = Decimal(str(settings.buy_points_per_kg))
        mass = self._resolve_buy_mass(parsed, balance, rate, settings)
        cost = calculate_buy_points(mass, rate)
        if cost > STREAMELEMENTS_POINTS_MAX:
            operation = self._create_operation(
                idempotency_key=idempotency_key,
                operation_type="buy",
                source="twitch",
                channel=channel,
                integration=integration,
                user=user,
                parsed=parsed,
                mass=mass,
                points=0,
                points_calculated=cost,
                rate=rate,
                settings=settings,
                mass_before=self._decimal(user.current_mass),
                balance_before=balance,
                source_request_id=source_request_id,
            )
            operation.provider_points_cap = STREAMELEMENTS_POINTS_MAX
            operation.provider_points_headroom_before = provider_headroom(balance)
            operation.state = "failed"
            operation.error_code = "ECONOMY_AMOUNT_EXCEEDS_PROVIDER_RANGE"
            operation.reconciliation_reason = "provider_cap"
            count_economy_provider_cap_rejection("buy")
            self._append_event(
                operation,
                "provider_balance_read",
                "processing",
                "failed",
                {
                    "balance": balance,
                    "headroom": operation.provider_points_headroom_before,
                    "cap": STREAMELEMENTS_POINTS_MAX,
                },
            )
            response = self._message(
                channel,
                MsgKey.ECONOMY_CAP_EXCEEDED,
                cap=format_large_number_points(STREAMELEMENTS_POINTS_MAX),
                operation_id=str(operation.id),
            )
            operation.response_payload = response.model_dump(mode="json")
            self._mark_outbox(operation, "dead_letter")
            self.db.commit()
            return response
        self._validate_limits(mass, settings)
        if balance < cost:
            return self._message(
                channel,
                MsgKey.BUY_FAIL_FUNDS,
                balance=format_large_number_points(balance),
                cost=format_large_number_points(cost),
            )
        validate_debit(balance, cost)
        operation = self._create_operation(
            idempotency_key=idempotency_key,
            operation_type="buy",
            source="twitch",
            channel=channel,
            integration=integration,
            user=user,
            parsed=parsed,
            mass=mass,
            points=-cost,
            rate=rate,
            settings=settings,
            mass_before=self._decimal(user.current_mass),
            balance_before=balance,
            source_request_id=source_request_id,
        )
        operation.provider_points_cap = STREAMELEMENTS_POINTS_MAX
        operation.provider_points_headroom_before = provider_headroom(balance)
        operation.provider_points_headroom_after = provider_headroom(balance - cost)
        operation.state = "external_pending"
        self._append_event(
            operation,
            "provider_balance_read",
            "processing",
            "external_pending",
            {
                "balance": balance,
                "headroom": operation.provider_points_headroom_before,
                "cap": STREAMELEMENTS_POINTS_MAX,
            },
        )
        self._mark_outbox(operation, "processing")
        self.db.commit()
        return await self._execute_buy(operation, channel, integration, token, settings)

    def rate(self, channel_id: str) -> dict[str, str | bool | int]:
        channel = self.channel_repo.get_by_twitch_id(channel_id)
        if not channel:
            raise EconomyDomainError("ECONOMY_SETTINGS_NOT_FOUND", "Channel not found.")
        settings = self._settings(channel)
        return {
            "pricing_mode": settings.pricing_mode,
            "buy_points_per_kg": str(settings.buy_points_per_kg),
            "sell_points_per_kg": str(settings.sell_points_per_kg),
            "buy_enabled": settings.buy_enabled,
            "sell_enabled": settings.sell_enabled,
            "version": settings.version,
        }

    async def _execute_sell(self, operation, channel, integration, token, settings) -> FishResponse:
        self._mark_started(operation)
        try:
            result = await self.se_client.add_points(
                str(integration.provider_channel_id),
                token,
                operation.twitch_username,
                operation.points_delta,
            )
            operation.external_applied = True
            operation.external_applied_at = datetime.now(timezone.utc)
            balance_after = result.balance_after
            if balance_after is None:
                balance_after = await self.se_client.get_balance(
                    str(integration.provider_channel_id), token, operation.twitch_username
                )
            balance_after = validate_provider_balance(balance_after)
            operation.provider_balance_after = balance_after
            operation.provider_status_code = result.status_code
            operation.provider_points_headroom_after = provider_headroom(balance_after)
            self._finish_attempt(operation, "confirmed", result=result)
            operation.state = "completed"
            operation.completed_at = datetime.now(timezone.utc)
            operation.player_mass_after = self._decimal(self._user_mass(operation.user_id))
            self._append_event(operation, "provider_write_confirmed", "processing", "completed")
            self._append_event(operation, "operation_completed", "completed", "completed")
            self._mark_outbox(operation, "processed")
            response = self._message(
                channel,
                MsgKey.SELL_MASS_SUCCESS,
                mass=format_large_number_mass(operation.mass_effective),
                amount=format_large_number_points(operation.points_delta),
                rate=self._format_rate(operation.rate_used_snapshot),
                balance=format_large_number_points(operation.provider_balance_after),
                remaining_mass=format_large_number_mass(operation.player_mass_after),
                operation_id=str(operation.id),
            )
            operation.response_payload = response.model_dump(mode="json")
            self.db.commit()
            return response
        except ProviderAmbiguousWriteError as error:
            self._finish_attempt(operation, "ambiguous", error=error)
            return self._ambiguous(operation, channel, error, "sell")
        except ProviderConnectionNotSentError as error:
            self._finish_attempt(operation, "not_sent", error=error)
            return self._queue_retry(operation, channel, error, "sell")
        except (
            ProviderAuthenticationError,
            ProviderValidationError,
            ProviderRateLimitError,
        ) as error:
            self._finish_attempt(operation, "rejected", error=error)
            if isinstance(error, ProviderRateLimitError):
                return self._queue_retry(operation, channel, error, "sell")
            self._restore_sell(operation)
            response = self._message(
                channel, MsgKey.SELL_MASS_FAILED, operation_id=str(operation.id)
            )
            operation.response_payload = response.model_dump(mode="json")
            self.db.commit()
            return response
        except Exception as error:  # noqa: BLE001
            self.db.rollback()
            return self._reconcile_sell_after_failure(operation.id, channel, error)

    async def _execute_buy(self, operation, channel, integration, token, settings) -> FishResponse:
        self._mark_started(operation)
        try:
            result = await self.se_client.add_points(
                str(integration.provider_channel_id),
                token,
                operation.twitch_username,
                operation.points_delta,
            )
            operation.external_applied = True
            operation.external_applied_at = datetime.now(timezone.utc)
            balance_after = result.balance_after
            if balance_after is None:
                balance_after = await self.se_client.get_balance(
                    str(integration.provider_channel_id), token, operation.twitch_username
                )
            balance_after = validate_provider_balance(balance_after)
            operation.provider_balance_after = balance_after
            operation.provider_status_code = result.status_code
            operation.provider_points_headroom_after = provider_headroom(balance_after)
            self._finish_attempt(operation, "confirmed", result=result)
            operation.state = "external_applied"
            user = (
                self.db.query(UserProgress)
                .filter(UserProgress.id == operation.user_id)
                .with_for_update()
                .one()
            )
            apply_mass_mutation(user, Decimal(str(operation.mass_effective)), track_total=True)
            operation.player_mass_after = self._decimal(user.current_mass)
            operation.internal_applied_at = datetime.now(timezone.utc)
            operation.completed_at = datetime.now(timezone.utc)
            operation.state = "completed"
            self._append_event(
                operation, "provider_write_confirmed", "processing", "external_applied"
            )
            self._append_event(operation, "local_mass_applied", "external_applied", "completed")
            self._mark_outbox(operation, "processed")
            response = self._message(
                channel,
                MsgKey.BUY_SUCCESS,
                mass=format_large_number_mass(operation.mass_effective),
                cost=format_large_number_points(-operation.points_delta),
                rate=self._format_rate(operation.rate_used_snapshot),
                balance=format_large_number_points(operation.provider_balance_after),
                new_mass=format_large_number_mass(operation.player_mass_after),
                operation_id=str(operation.id),
            )
            operation.response_payload = response.model_dump(mode="json")
            self.db.commit()
            return response
        except ProviderAmbiguousWriteError as error:
            self._finish_attempt(operation, "ambiguous", error=error)
            return self._ambiguous(operation, channel, error, "buy")
        except ProviderConnectionNotSentError as error:
            self._finish_attempt(operation, "not_sent", error=error)
            return self._queue_retry(operation, channel, error, "buy")
        except (
            ProviderAuthenticationError,
            ProviderValidationError,
            ProviderRateLimitError,
        ) as error:
            self._finish_attempt(operation, "rejected", error=error)
            if isinstance(error, ProviderRateLimitError):
                return self._queue_retry(operation, channel, error, "buy")
            operation.state = "failed"
            operation.error_code = error.code
            operation.last_error = error.code
            self._mark_outbox(operation, "dead_letter")
            response = self._message(
                channel, MsgKey.BUY_INVALID_AMOUNT, operation_id=str(operation.id)
            )
            operation.response_payload = response.model_dump(mode="json")
            self.db.commit()
            return response
        # Any local mutation failure after provider debit requires the same
        # full-refund-or-reconciliation boundary, including database errors.
        except Exception as error:  # noqa: BLE001
            self.db.rollback()
            return await self._compensate_buy(operation.id, channel, integration, token, error)

    async def _compensate_buy(
        self, operation_id, channel, integration, token, error
    ) -> FishResponse:
        operation = (
            self.db.query(EconomyOperation)
            .filter(EconomyOperation.id == operation_id)
            .with_for_update()
            .one()
        )
        try:
            current_balance = validate_provider_balance(
                await self.se_client.get_balance(
                    str(integration.provider_channel_id), token, operation.twitch_username
                )
            )
            validate_credit(current_balance, -operation.points_delta)
            result = await self.se_client.add_points(
                str(integration.provider_channel_id),
                token,
                operation.twitch_username,
                -operation.points_delta,
            )
            if result.balance_after is not None:
                validate_provider_balance(result.balance_after)
        except ProviderError as compensation_error:
            operation.state = "reconciliation_required"
            operation.reconciliation_reason = (
                "provider_cap_blocks_full_compensation"
                if compensation_error.code == "STREAMELEMENTS_POINTS_CAP_EXCEEDED"
                else compensation_error.code
            )
            operation.last_error = compensation_error.code
            if operation.reconciliation_reason == "provider_cap_blocks_full_compensation":
                count_economy_reconciliation("provider_cap")
            response = self._message(
                channel, MsgKey.BUY_INVALID_AMOUNT, operation_id=str(operation.id)
            )
            self._mark_outbox(operation, "reconciliation_required")
        except EconomyDomainError as compensation_error:
            operation.state = "reconciliation_required"
            operation.reconciliation_reason = "provider_cap_blocks_full_compensation"
            operation.error_code = compensation_error.code
            operation.last_error = compensation_error.code
            count_economy_reconciliation("provider_cap")
            response = self._message(
                channel, MsgKey.ECONOMY_RECONCILIATION_REQUIRED, operation_id=str(operation.id)
            )
            self._mark_outbox(operation, "reconciliation_required")
        else:
            operation.state = "compensated"
            operation.compensation_state = "confirmed"
            operation.last_error = type(error).__name__
            response = self._message(
                channel, MsgKey.BUY_INVALID_AMOUNT, operation_id=str(operation.id)
            )
            self._mark_outbox(operation, "compensated")
        operation.response_payload = response.model_dump(mode="json")
        self.db.commit()
        return response

    def _queue_retry(self, operation, channel, error, operation_type: str) -> FishResponse:
        operation.state = "queued"
        operation.last_error = error.code
        operation.error_code = error.code
        self._append_event(operation, "provider_write_started", "processing", "queued")
        self._mark_outbox(operation, "pending")
        self.db.commit()
        return self._message(channel, MsgKey.ECONOMY_PROCESSING, operation_id=str(operation.id))

    def _ambiguous(self, operation, channel, error, operation_type: str) -> FishResponse:
        operation.state = "reconciliation_required"
        operation.reconciliation_reason = error.code
        count_economy_reconciliation(
            "provider_cap" if error.code == "STREAMELEMENTS_POINTS_CAP_EXCEEDED" else error.code
        )
        operation.error_code = error.code
        operation.last_error = error.code
        self._append_event(
            operation, "provider_write_ambiguous", "processing", "reconciliation_required"
        )
        self._mark_outbox(operation, "reconciliation_required")
        response = self._message(
            channel, MsgKey.ECONOMY_RECONCILIATION_REQUIRED, operation_id=str(operation.id)
        )
        operation.response_payload = response.model_dump(mode="json")
        self.db.commit()
        return response

    def _create_operation(
        self,
        *,
        idempotency_key,
        operation_type,
        source,
        channel,
        integration,
        user,
        parsed,
        mass,
        points,
        rate,
        settings,
        mass_before,
        balance_before=None,
        source_request_id=None,
        points_calculated=None,
    ):
        operation = EconomyOperation(
            idempotency_key=idempotency_key,
            operation_type=operation_type,
            channel_id=channel.id,
            user_id=user.id,
            twitch_username=(user.username or "").strip(),
            provider="streamelements",
            integration_id=integration.id,
            source=source,
            source_request_id=source_request_id,
            provider_channel_id_snapshot=integration.provider_channel_id,
            raw_command_argument=parsed.raw,
            argument_mode=parsed.mode,
            argument_unit=parsed.unit,
            argument_multiplier_kg=parsed.multiplier_kg,
            mass_effective=mass,
            pricing_mode_snapshot=settings.pricing_mode,
            buy_rate_snapshot=settings.buy_points_per_kg,
            sell_rate_snapshot=settings.sell_points_per_kg,
            rate_used_snapshot=rate,
            settings_version_snapshot=settings.version,
            player_mass_before=mass_before,
            provider_balance_before=balance_before,
            mass_delta=-mass if operation_type == "sell" else mass,
            points_delta=points,
            points_calculated=points_calculated if points_calculated is not None else abs(points),
            state="processing",
        )
        self.db.add(operation)
        self.db.flush()
        self._append_event(operation, "operation_created", None, "processing")
        self.db.add(
            OutboxEvent(
                idempotency_key=f"economy:{operation.id}",
                topic="streamelements.points",
                payload={"operation_id": str(operation.id)},
            )
        )
        self.db.flush()
        return operation

    def _load_context(self, twitch_id, channel_id, *, lock: bool):
        channel = self.channel_repo.get_by_twitch_id(channel_id)
        if not channel:
            raise EconomyDomainError("ECONOMY_SETTINGS_NOT_FOUND", "Channel not found.")
        query = self.db.query(UserProgress).filter(
            UserProgress.user_twitch_id == twitch_id, UserProgress.channel_id == channel.id
        )
        if lock:
            query = query.with_for_update()
        user = query.first()
        if not user:
            return None, channel, None, None
        integration = (
            self.db.query(ChannelIntegration)
            .filter(
                ChannelIntegration.channel_id == channel.id,
                ChannelIntegration.provider == "streamelements",
            )
            .first()
        )
        if not integration or integration.status != "connected":
            raise EconomyDomainError(
                "STREAM_ELEMENTS_NOT_CONFIGURED", "StreamElements integration is not configured."
            )
        settings = self._settings(channel)
        return user, channel, integration, settings

    @contextmanager
    def _buy_request_lock(self, channel_id: str, twitch_id: str):
        redis = RedisClient.get_client()
        key = f"economy:buy:{channel_id}:{twitch_id}"
        token = uuid4().hex
        if not redis.set(key, token, nx=True, ex=120):
            raise EconomyDomainError(
                "ECONOMY_OPERATION_IN_PROGRESS",
                "Another fish purchase is already processing. Please wait.",
            )
        try:
            yield
        finally:
            redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] "
                "then return redis.call('del', KEYS[1]) else return 0 end",
                1,
                key,
                token,
            )

    @contextmanager
    def _sell_request_lock(self, channel_id: str, twitch_id: str):
        redis = RedisClient.get_client()
        key = f"economy:sell:{channel_id}:{twitch_id}"
        token = uuid4().hex
        if not redis.set(key, token, nx=True, ex=120):
            raise EconomyDomainError(
                "ECONOMY_OPERATION_IN_PROGRESS",
                "Another fish sale is already processing. Please wait.",
            )
        try:
            yield
        finally:
            redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] "
                "then return redis.call('del', KEYS[1]) else return 0 end",
                1,
                key,
                token,
            )

    def _lock_user(self, user_id: int) -> UserProgress:
        """Lock one player only for the local state transition."""

        return (
            self.db.query(UserProgress)
            .filter(UserProgress.id == user_id)
            .with_for_update()
            .one()
        )

    def _settings(self, channel: Channel) -> ChannelEconomySettings:
        row = (
            self.db.query(ChannelEconomySettings)
            .filter(ChannelEconomySettings.channel_id == channel.id)
            .first()
        )
        if row:
            return row
        custom = (channel.config or {}).get("custom_params", {})
        row = ChannelEconomySettings(
            channel_id=channel.id,
            buy_points_per_kg=Decimal(str(custom.get("buy_rate", "120"))),
            sell_points_per_kg=Decimal(str(custom.get("sell_rate", "100"))),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _decrypt_integration(self, integration, channel):
        try:
            return decrypt_integration_token(
                integration.credential_ciphertext, key_version=integration.credential_key_version
            )
        except ValueError:
            try:
                return decrypt_token(channel.se_token or integration.credential_ciphertext)
            except ValueError as error:
                raise EconomyDomainError(
                    "STREAM_ELEMENTS_INVALID_CREDENTIALS",
                    "StreamElements credentials are unavailable.",
                ) from error

    def _resolve_sell_mass(
        self, parsed: ParsedMassArgument, current_mass: Decimal, settings, provider_balance: int
    ) -> Decimal:
        mass = current_mass if parsed.mode == "all" else parsed.mass_kg
        assert mass is not None
        if parsed.mode == "all":
            mass = max_sell_mass(provider_balance, Decimal(str(settings.sell_points_per_kg)), mass)
        mass = min(mass, current_mass, Decimal(str(settings.max_transaction_mass)))
        mass = mass.quantize(MASS_QUANTUM, rounding=ROUND_FLOOR)
        if mass <= 0 and parsed.mode == "all":
            raise EconomyDomainError(
                "ECONOMY_NO_SELLABLE_MASS",
                "No mass can be sold within the StreamElements points limit.",
            )
        self._validate_limits(mass, settings)
        return mass

    def _resolve_buy_mass(self, parsed, balance: int, rate: Decimal, settings) -> Decimal:
        max_mass = Decimal(str(settings.max_transaction_mass))
        if parsed.mode == "all":
            mass = max_buy_mass(balance, rate, max_mass)
            if mass < Decimal(str(settings.min_transaction_mass)):
                raise EconomyDomainError(
                    "ECONOMY_NO_PURCHASABLE_MASS",
                    "You do not have enough StreamElements points to buy the minimum mass amount.",
                )
            return mass
        assert parsed.mass_kg is not None
        return parsed.mass_kg

    def _validate_limits(self, mass: Decimal, settings) -> None:
        if mass < Decimal(str(settings.min_transaction_mass)):
            raise EconomyDomainError(
                "ECONOMY_TRANSACTION_TOO_SMALL", "Transaction mass is below the channel minimum."
            )
        if mass > Decimal(str(settings.max_transaction_mass)):
            raise EconomyDomainError(
                "ECONOMY_TRANSACTION_TOO_LARGE", "Transaction mass exceeds the channel maximum."
            )

    def _append_event(self, operation, event_type, from_state, to_state, metadata=None):
        sequence = getattr(operation, "_event_sequence", None)
        if sequence is None:
            last = (
                self.db.query(EconomyOperationEvent.sequence_no)
                .filter(EconomyOperationEvent.operation_id == operation.id)
                .order_by(EconomyOperationEvent.sequence_no.desc())
                .first()
            )
            sequence = last[0] if last else 0
        sequence += 1
        operation._event_sequence = sequence
        self.db.add(
            EconomyOperationEvent(
                operation_id=operation.id,
                sequence_no=sequence,
                event_type=event_type,
                from_state=from_state,
                to_state=to_state,
                actor_type="system",
                event_metadata=metadata or {},
            )
        )

    def _mark_started(self, operation):
        operation.started_at = operation.started_at or datetime.now(timezone.utc)
        operation.state = "processing"
        attempt = EconomyProviderAttempt(
            operation_id=operation.id,
            attempt_no=operation.attempts + 1,
            request_kind="add_points",
            points_delta=operation.points_delta,
            provider_balance_before=operation.provider_balance_before,
            provider_points_cap=STREAMELEMENTS_POINTS_MAX,
            request_started_at=datetime.now(timezone.utc),
            outcome="started",
        )
        self.db.add(attempt)
        operation.attempts += 1
        self._append_event(operation, "provider_write_started", "processing", "processing")
        return attempt

    def _finish_attempt(self, operation, outcome, *, result=None, error=None):
        attempt = (
            self.db.query(EconomyProviderAttempt)
            .filter(EconomyProviderAttempt.operation_id == operation.id)
            .order_by(EconomyProviderAttempt.attempt_no.desc())
            .first()
        )
        if not attempt:
            return
        finished_at = datetime.now(timezone.utc)
        attempt.request_finished_at = finished_at
        attempt.latency_ms = max(
            int((finished_at - attempt.request_started_at).total_seconds() * 1000), 0
        )
        attempt.outcome = outcome
        if result is not None:
            attempt.provider_balance_after = result.balance_after
            attempt.http_status = result.status_code
            attempt.provider_request_id = result.provider_request_id
        if error is not None:
            attempt.error_code = getattr(error, "code", type(error).__name__)
            attempt.error_message = type(error).__name__

    def _restore_sell(self, operation):
        user = (
            self.db.query(UserProgress)
            .filter(UserProgress.id == operation.user_id)
            .with_for_update()
            .one()
        )
        apply_mass_mutation(user, Decimal(str(-operation.mass_delta)), track_total=False)
        operation.compensated_at = datetime.now(timezone.utc)
        operation.compensation_state = "local_mass_restored"
        operation.state = "compensated"
        operation.external_applied = False
        self._append_event(operation, "local_mass_restored", "processing", "compensated")
        self._mark_outbox(operation, "compensated")

    def _reconcile_sell_after_failure(self, operation_id, channel, error) -> FishResponse:
        operation = (
            self.db.query(EconomyOperation)
            .filter(EconomyOperation.id == operation_id)
            .with_for_update()
            .one()
        )
        self._finish_attempt(operation, "ambiguous", error=error)
        operation.state = "reconciliation_required"
        operation.error_code = "ECONOMY_RECONCILIATION_REQUIRED"
        operation.last_error = type(error).__name__
        operation.reconciliation_reason = "local_persistence_failure_after_provider_write"
        self._append_event(
            operation,
            "local_persistence_failed",
            "processing",
            "reconciliation_required",
        )
        self._mark_outbox(operation, "reconciliation_required")
        count_economy_reconciliation("local_persistence_failure")
        response = self._message(
            channel,
            MsgKey.ECONOMY_RECONCILIATION_REQUIRED,
            operation_id=str(operation.id),
        )
        operation.response_payload = response.model_dump(mode="json")
        self.db.commit()
        return response

    def _mark_outbox(self, operation, state: str) -> None:
        event = (
            self.db.query(OutboxEvent)
            .filter(OutboxEvent.idempotency_key == f"economy:{operation.id}")
            .first()
        )
        if event:
            event.state = state
            if state == "processing":
                event.lease_expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=self.EXTERNAL_OPERATION_LEASE_SECONDS
                )
            else:
                event.lease_expires_at = None
            if state == "pending":
                event.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=1)
            if state == "processed":
                event.processed_at = datetime.now(timezone.utc)

    def _user_mass(self, user_id):
        user = self.db.query(UserProgress).filter(UserProgress.id == user_id).first()
        return user.current_mass if user else Decimal(0)

    def _get_operation(self, key, *, operation_type: str, raw_argument: str | None):
        operation = (
            self.db.query(EconomyOperation).filter(EconomyOperation.idempotency_key == key).first()
        )
        if operation is None:
            return None
        normalized_argument = str(raw_argument or "").strip().lower()
        if (
            operation.operation_type != operation_type
            or (operation.raw_command_argument or "").strip().lower() != normalized_argument
        ):
            raise EconomyDomainError(
                "IDEMPOTENCY_CONFLICT",
                "This idempotency key was already used with a different operation.",
            )
        return operation

    def _stored_response(self, operation):
        if operation.response_payload:
            response = FishResponse.model_validate(operation.response_payload)
            response.is_replayed = True
            return response
        raise EconomyDomainError(
            "ECONOMY_OPERATION_IN_PROGRESS", "This economy operation is already processing."
        )

    def _message(self, channel, key, **kwargs):
        response = FishResponse(
            chat_message=resolve_message(channel.config or {}, key, **kwargs),
            xp_gained=0,
            actions=[],
        )
        response.operation_id = kwargs.get("operation_id")
        return response

    @staticmethod
    def _decimal(value):
        return Decimal(str(value or 0)).quantize(MASS_QUANTUM)

    @staticmethod
    def _format_rate(value):
        return format(Decimal(str(value)).normalize(), "f")

    @staticmethod
    def _require_key(key):
        if not str(key or "").strip():
            raise EconomyDomainError("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")

    # Kept as a compatibility helper for old callers; conversion pricing never
    # invokes player modifiers anymore.
    def _effective_rate(self, user, base_rate: Decimal, stat: StatKey) -> Decimal:
        modifier = self.modifier_service.resolve(user, ModifierScope.ECONOMY).value(stat)
        if stat == StatKey.BUY_DISCOUNT_PCT:
            return base_rate * (Decimal(1) - modifier)
        return base_rate * (Decimal(1) + modifier)
