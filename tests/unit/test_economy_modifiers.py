from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from domain.item_schema import StatKey
from services.economy_service import EconomyService


def test_economy_rates_apply_typed_sell_bonus_and_buy_discount() -> None:
    values = {
        StatKey.SELL_RATE_BONUS_PCT: Decimal("0.50"),
        StatKey.BUY_DISCOUNT_PCT: Decimal("0.25"),
    }
    resolved = SimpleNamespace(value=lambda stat: values[stat])
    service = object.__new__(EconomyService)
    service.modifier_service = Mock()
    service.modifier_service.resolve.return_value = resolved
    user = SimpleNamespace(id=1)

    assert service._effective_rate(
        user, Decimal("100"), StatKey.SELL_RATE_BONUS_PCT
    ) == Decimal("150.00")
    assert service._effective_rate(
        user, Decimal("100"), StatKey.BUY_DISCOUNT_PCT
    ) == Decimal("75.00")
