from decimal import Decimal

import pytest
from core.messages import DEFAULT_MESSAGES, MsgKey
from domain.economy import (
    calculate_buy_points,
    calculate_sell_points,
    parse_mass_argument,
)
from integrations.streamelements.constants import (
    STREAMELEMENTS_POINTS_MAX,
    max_buy_mass,
    max_sell_mass,
    validate_credit,
    validate_provider_balance,
)


def test_provider_cap_is_single_shared_constant() -> None:
    assert STREAMELEMENTS_POINTS_MAX == 2_147_483_647


def test_provider_cap_message_does_not_expose_terminal_operation_id() -> None:
    message = DEFAULT_MESSAGES[MsgKey.ECONOMY_CAP_EXCEEDED]
    assert "{operation_id}" not in message
    assert "Operation:" not in message


def test_buy_all_uses_mass_quantum_and_ceiling() -> None:
    mass = max_buy_mass(STREAMELEMENTS_POINTS_MAX, Decimal(1000), Decimal(999999999))
    assert mass == Decimal("2147483.64")
    assert calculate_buy_points(mass, Decimal(1000)) == 2_147_483_640


def test_sell_all_is_limited_by_provider_headroom() -> None:
    mass = max_sell_mass(2_147_483_600, Decimal(1000), Decimal(1000))
    assert mass == Decimal("0.04")
    assert calculate_sell_points(mass, Decimal(1000)) == 40


def test_exact_sell_over_cap_is_rejected_without_clamping() -> None:
    with pytest.raises(ValueError) as error:
        validate_credit(2_147_483_000, 1000)
    assert error.value.code == "STREAMELEMENTS_POINTS_CAP_EXCEEDED"


def test_large_suffix_remains_mass_parser_concern() -> None:
    parsed = parse_mass_argument("5kt")
    assert parsed.mass_kg == Decimal("5000000.00")


def test_mass_parser_rejects_values_that_do_not_fit_persisted_numeric() -> None:
    with pytest.raises(ValueError) as error:
        parse_mass_argument("999999999999999999999999")
    assert error.value.code == "ECONOMY_INVALID_MASS"


def test_all_is_an_explicit_mass_argument_mode() -> None:
    parsed = parse_mass_argument("all")
    assert parsed.mode == "all"
    assert parsed.mass_kg is None


def test_buy_all_returns_no_mass_when_balance_cannot_buy_one_quantum() -> None:
    assert max_buy_mass(9, Decimal(1000), Decimal(1000)) == Decimal("0.00")


def test_sell_all_returns_no_mass_at_provider_cap() -> None:
    assert max_sell_mass(STREAMELEMENTS_POINTS_MAX, Decimal(1000), Decimal(1000)) == Decimal(
        "0.00"
    )


def test_invalid_provider_balance_is_rejected() -> None:
    with pytest.raises(ValueError) as error:
        validate_provider_balance(STREAMELEMENTS_POINTS_MAX + 1)
    assert error.value.code == "STREAMELEMENTS_BALANCE_INVALID"
