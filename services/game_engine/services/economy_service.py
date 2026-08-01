from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from core.game_params import GParam, resolve_param
from core.messages import (
    MsgKey,
    format_large_number_mass,
    format_large_number_points,
    resolve_message,
)
from core.security import decrypt_token
from domain.schemas.fishing import FishResponse
from infrastructure.models import EconomyOperation, OutboxEvent
from infrastructure.repositories.channel_repo import ChannelRepository
from infrastructure.repositories.user_repo import UserRepository
from infrastructure.se_client import SEApiClient


MASS_QUANTUM = Decimal("0.01")


class EconomyService:
    def __init__(
        self,
        user_repo: UserRepository,
        channel_repo: ChannelRepository,
        se_client: SEApiClient,
    ):
        self.user_repo = user_repo
        self.channel_repo = channel_repo
        self.se_client = se_client
        self.db = user_repo.db

    def sell_fish(
        self,
        twitch_id: str,
        channel_id: str,
        amount_str: str | None,
        idempotency_key: str,
    ) -> FishResponse:
        previous = self._get_operation(idempotency_key)
        if previous:
            return self._stored_response(previous)

        user = self.user_repo.get_progress(twitch_id, channel_id)
        if not user:
            return self._response({}, MsgKey.ERR_NO_PROFILE, username=twitch_id)

        channel_config = user.channel.config or {}
        channel = user.channel
        if not channel.se_token or not channel.se_channel_id:
            return self._response(channel_config, MsgKey.SE_NOT_CONFIGURED)

        current_mass = max(self._decimal(user.current_mass), Decimal("0"))
        if current_mass <= 0:
            return self._response(channel_config, MsgKey.SELL_MASS_EMPTY)

        mass_to_sell = self._parse_mass_amount(amount_str, current_mass, allow_all=True)
        if mass_to_sell is None:
            return self._response(channel_config, MsgKey.SELL_MASS_INVALID_AMOUNT)

        custom_params = channel_config.get("custom_params", {})
        sell_rate = Decimal(str(resolve_param(custom_params, GParam.SELL_RATE)))
        points = int((mass_to_sell * sell_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if points <= 0:
            return self._response(channel_config, MsgKey.SELL_MASS_INVALID_AMOUNT)

        response = self._response(
            channel_config,
            MsgKey.SELL_MASS_SUCCESS,
            mass=format_large_number_mass(float(mass_to_sell)),
            amount=format_large_number_points(points),
            rate=self._format_rate(sell_rate),
        )
        operation = EconomyOperation(
            idempotency_key=idempotency_key,
            operation_type="sell",
            channel_id=channel.id,
            user_id=user.id,
            twitch_username=(user.username or "").strip() or twitch_id,
            mass_delta=-mass_to_sell,
            points_delta=points,
            state="pending",
            response_payload=response.model_dump(mode="json"),
        )
        self.db.add(operation)
        self.db.flush()
        self.db.add(
            OutboxEvent(
                idempotency_key=f"economy:{operation.id}",
                topic="streamelements.points",
                payload={"operation_id": operation.id},
            )
        )
        user.current_mass = (current_mass - mass_to_sell).quantize(MASS_QUANTUM)
        self.db.flush()
        return response

    def buy_fish(
        self,
        twitch_id: str,
        channel_id: str,
        amount_str: str | None,
        idempotency_key: str,
    ) -> FishResponse:
        previous = self._get_operation(idempotency_key)
        if previous:
            return self._stored_response(previous)

        user = self.user_repo.get_progress(twitch_id, channel_id)
        if not user:
            return self._response({}, MsgKey.ERR_NO_PROFILE, username=twitch_id)

        channel_config = user.channel.config or {}
        channel = user.channel
        if not channel.se_token or not channel.se_channel_id:
            return self._response(channel_config, MsgKey.SE_NOT_CONFIGURED)

        try:
            plain_token = decrypt_token(channel.se_token)
        except ValueError:
            return self._response(channel_config, MsgKey.SE_NOT_CONFIGURED)

        mass_to_buy = self._parse_mass_amount(amount_str, None, allow_all=False)
        if mass_to_buy is None:
            return self._response(channel_config, MsgKey.BUY_INVALID_AMOUNT)

        custom_params = channel_config.get("custom_params", {})
        buy_rate = Decimal(str(resolve_param(custom_params, GParam.BUY_RATE)))
        cost = int((mass_to_buy * buy_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if cost <= 0:
            return self._response(channel_config, MsgKey.BUY_INVALID_AMOUNT)

        target_username = (user.username or "").strip() or twitch_id
        se_channel_id = str(channel.se_channel_id).strip()
        balance = self.se_client.get_balance_sync(se_channel_id, plain_token, target_username)
        if balance < cost:
            return self._response(
                channel_config,
                MsgKey.BUY_FAIL_FUNDS,
                balance=format_large_number_points(balance),
                cost=format_large_number_points(cost),
            )

        operation = EconomyOperation(
            idempotency_key=idempotency_key,
            operation_type="buy",
            channel_id=channel.id,
            user_id=user.id,
            twitch_username=target_username,
            mass_delta=mass_to_buy,
            points_delta=-cost,
            state="external_pending",
        )
        self.db.add(operation)
        self.db.commit()

        try:
            self.se_client.add_points_sync(se_channel_id, plain_token, target_username, -cost)
            operation.external_applied = True
            operation.state = "external_applied"
            self.db.commit()

            user.current_mass = (self._decimal(user.current_mass) + mass_to_buy).quantize(MASS_QUANTUM)
            user.total_mass_stat = (
                self._decimal(user.total_mass_stat) + mass_to_buy
            ).quantize(MASS_QUANTUM)
            response = self._response(
                channel_config,
                MsgKey.BUY_SUCCESS,
                mass=format_large_number_mass(float(mass_to_buy)),
                cost=format_large_number_points(cost),
                rate=self._format_rate(buy_rate),
            )
            operation.response_payload = response.model_dump(mode="json")
            operation.state = "completed"
            self.db.commit()
            return response
        except Exception:
            self.db.rollback()
            if operation.external_applied:
                self._compensate_buy(operation, channel, plain_token, cost)
            raise

    def _compensate_buy(
        self,
        operation: EconomyOperation,
        channel,
        plain_token: str,
        cost: int,
    ) -> None:
        try:
            self.se_client.add_points_sync(
                str(channel.se_channel_id),
                plain_token,
                operation.twitch_username,
                cost,
            )
            operation.state = "compensated"
            operation.external_applied = False
            operation.last_error = "Internal update failed; external points were restored"
        except Exception as compensation_error:
            operation.state = "reconciliation_required"
            operation.last_error = type(compensation_error).__name__
        self.db.add(operation)
        self.db.commit()

    def _get_operation(self, idempotency_key: str) -> EconomyOperation | None:
        return (
            self.db.query(EconomyOperation)
            .filter(EconomyOperation.idempotency_key == idempotency_key)
            .first()
        )

    def _stored_response(self, operation: EconomyOperation) -> FishResponse:
        if operation.response_payload:
            return FishResponse.model_validate(operation.response_payload)
        if operation.state in {"external_pending", "external_applied"}:
            raise ValueError("Operation is already in progress")
        raise ValueError(f"Operation cannot be repeated in state '{operation.state}'")

    def _response(self, channel_config: dict, key: MsgKey, **kwargs) -> FishResponse:
        return FishResponse(
            chat_message=resolve_message(channel_config or {}, key, **kwargs),
            xp_gained=0,
            actions=[],
        )

    def _parse_mass_amount(
        self,
        amount_str: str | None,
        max_mass: Decimal | None,
        allow_all: bool,
    ) -> Decimal | None:
        raw = (amount_str or "").strip().lower()
        if not raw:
            return max_mass if allow_all and max_mass is not None else None
        if raw == "all":
            return max_mass if allow_all and max_mass is not None else None
        try:
            value = Decimal(raw).quantize(MASS_QUANTUM, rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return None
        if value <= 0 or (max_mass is not None and value > max_mass):
            return None
        return value

    def _decimal(self, value: object) -> Decimal:
        return Decimal(str(value or 0)).quantize(MASS_QUANTUM, rounding=ROUND_HALF_UP)

    def _format_rate(self, rate: Decimal) -> str:
        normalized = rate.quantize(MASS_QUANTUM).normalize()
        return format(normalized, "f")
