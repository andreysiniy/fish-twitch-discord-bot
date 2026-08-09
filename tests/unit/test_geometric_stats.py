from decimal import Decimal

import pytest

from domain.logic.formulas import geometric_first_success_stats


def test_geometric_first_success_fair_coin() -> None:
    expected, p50, p90 = geometric_first_success_stats(Decimal("0.5"))
    assert expected == Decimal("2.0")
    assert p50 == 1
    assert p90 == 4


def test_geometric_first_success_low_probability() -> None:
    expected, p50, p90 = geometric_first_success_stats(Decimal("0.05"))
    assert expected == Decimal("20.0")
    assert p50 == 14
    assert p90 == 45


def test_geometric_first_success_accepts_float_decimal() -> None:
    expected, p50, p90 = geometric_first_success_stats(Decimal("0.10"))
    assert expected == Decimal("10.0")
    assert p50 == 7
    assert p90 == 22


def test_geometric_first_success_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        geometric_first_success_stats(Decimal("0"))
    with pytest.raises(ValueError):
        geometric_first_success_stats(Decimal("1"))
