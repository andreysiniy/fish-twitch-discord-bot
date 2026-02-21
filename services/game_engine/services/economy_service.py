import json

from redis import Redis

from core.game_params import GParam, resolve_param
from core.messages import (
    MsgKey,
    format_large_number_mass,
    format_large_number_points,
    resolve_message,
)
from core.security import decrypt_token
from domain.schemas.admin import ChannelUpdateDTO
from domain.schemas.fishing import FishResponse
from infrastructure.repositories.channel_repo import ChannelRepository
from infrastructure.repositories.user_repo import UserRepository
from infrastructure.se_client import SEApiClient


class EconomyService:
    QUEUE_NAME = "se_points_queue"

    def __init__(
        self,
        user_repo: UserRepository,
        channel_repo: ChannelRepository,
        redis_client: Redis,
        se_client: SEApiClient,
    ):
        self.user_repo = user_repo
        self.channel_repo = channel_repo
        self.redis_client = redis_client
        self.se_client = se_client

    def sell_fish(self, twitch_id: str, channel_id: str, amount_str: str | None) -> FishResponse:
        user = self.user_repo.get_progress(twitch_id, channel_id)
        if not user:
            return self._response({}, MsgKey.ERR_NO_PROFILE, username=twitch_id)

        channel_config = user.channel.config or {}
        channel = user.channel
        if not channel.se_token or not channel.se_channel_id:
            return self._response(channel_config, MsgKey.SE_NOT_CONFIGURED)

        current_mass = max(float(user.current_mass or 0.0), 0.0)
        if current_mass <= 0:
            return self._response(channel_config, MsgKey.SELL_MASS_EMPTY)

        mass_to_sell = self._parse_mass_amount(amount_str, current_mass, allow_all=True)
        if mass_to_sell is None:
            return self._response(channel_config, MsgKey.SELL_MASS_INVALID_AMOUNT)

        custom_params = channel_config.get("custom_params", {})
        sell_rate = float(resolve_param(custom_params, GParam.SELL_RATE))
        points = int(round(mass_to_sell * sell_rate))
        if points <= 0:
            return self._response(channel_config, MsgKey.SELL_MASS_INVALID_AMOUNT)

        user.current_mass = round(max(current_mass - mass_to_sell, 0.0), 2)
        self.user_repo.save_progress(user)
        target_username = (user.username or "").strip() or twitch_id

        job = {
            "channel_id": int(channel.id),
            "se_channel_id": str(channel.se_channel_id).strip(),
            "twitch_username": target_username,
            "amount": points,
        }
        self.redis_client.lpush(self.QUEUE_NAME, json.dumps(job))

        return self._response(
            channel_config,
            MsgKey.SELL_MASS_SUCCESS,
            mass=format_large_number_mass(mass_to_sell),
            amount=format_large_number_points(points),
            rate=self._format_rate(sell_rate),
        )

    async def buy_fish(self, twitch_id: str, channel_id: str, amount_str: str | None) -> FishResponse:
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
        buy_rate = float(resolve_param(custom_params, GParam.BUY_RATE))
        cost = int(round(mass_to_buy * buy_rate))
        if cost <= 0:
            return self._response(channel_config, MsgKey.BUY_INVALID_AMOUNT)

        target_username = (user.username or "").strip() or twitch_id
        se_channel_id = str(channel.se_channel_id).strip()
        try:
            balance = await self.se_client.get_balance(se_channel_id, plain_token, target_username)
            if balance < cost:
                return self._response(
                    channel_config,
                    MsgKey.BUY_FAIL_FUNDS,
                    balance=format_large_number_points(balance),
                    cost=format_large_number_points(cost),
                )
            await self.se_client.add_points(se_channel_id, plain_token, target_username, -cost)
        except PermissionError:
            self.channel_repo.update(channel.id, ChannelUpdateDTO(se_token=None))
            return self._response(channel_config, MsgKey.SE_NOT_CONFIGURED)
        except ValueError:
            return self._response(channel_config, MsgKey.ERR_GENERIC)

        user.current_mass = round(max(float(user.current_mass or 0.0) + mass_to_buy, 0.0), 2)
        user.total_mass_stat = round(max(float(user.total_mass_stat or 0.0) + mass_to_buy, 0.0), 2)
        self.user_repo.save_progress(user)

        return self._response(
            channel_config,
            MsgKey.BUY_SUCCESS,
            mass=format_large_number_mass(mass_to_buy),
            cost=format_large_number_points(cost),
            rate=self._format_rate(buy_rate),
        )

    def _response(self, channel_config: dict, key: MsgKey, **kwargs) -> FishResponse:
        return FishResponse(
            chat_message=resolve_message(channel_config or {}, key, **kwargs),
            xp_gained=0,
            actions=[],
        )

    def _parse_mass_amount(
        self,
        amount_str: str | None,
        max_mass: float | None,
        allow_all: bool,
    ) -> float | None:
        raw = (amount_str or "").strip().lower()
        if not raw:
            return max_mass if allow_all and max_mass is not None else None
        if raw == "all":
            if not allow_all or max_mass is None:
                return None
            return round(max_mass, 2)

        try:
            value = float(raw)
        except ValueError:
            return None

        if value <= 0:
            return None
        if max_mass is not None and value > max_mass:
            return None
        return round(value, 2)

    def _format_rate(self, rate: float) -> str:
        normalized = round(float(rate), 2)
        if normalized.is_integer():
            return str(int(normalized))
        return str(normalized)
