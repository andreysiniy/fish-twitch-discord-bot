"""StreamElements provider invariants shared by all engine use cases."""

from decimal import ROUND_FLOOR, Decimal

from domain.economy import (
    MASS_QUANTUM,
    EconomyDomainError,
    calculate_buy_points,
    calculate_sell_points,
    quantize_mass,
)

STREAMELEMENTS_POINTS_MAX = 2_147_483_647


def validate_provider_balance(balance: int) -> int:
    value = int(balance)
    if value < 0 or value > STREAMELEMENTS_POINTS_MAX:
        raise EconomyDomainError(
            "STREAMELEMENTS_BALANCE_INVALID",
            "The StreamElements balance is outside the supported points range.",
        )
    return value


def provider_headroom(balance: int) -> int:
    return STREAMELEMENTS_POINTS_MAX - validate_provider_balance(balance)


def validate_debit(balance: int, points: int) -> int:
    current = validate_provider_balance(balance)
    amount = int(points)
    if amount < 0 or amount > current:
        raise EconomyDomainError(
            "STREAMELEMENTS_BALANCE_TOO_LOW", "The StreamElements balance is too low."
        )
    return current - amount


def validate_credit(balance: int, points: int) -> int:
    current = validate_provider_balance(balance)
    amount = int(points)
    if amount < 0 or amount > provider_headroom(current):
        raise EconomyDomainError(
            "STREAMELEMENTS_POINTS_CAP_EXCEEDED",
            "The StreamElements points balance would exceed its provider limit.",
        )
    return current + amount


def max_buy_mass(balance: int, rate: Decimal, max_mass: Decimal) -> Decimal:
    current = validate_provider_balance(balance)
    if rate <= 0:
        raise EconomyDomainError("ECONOMY_INVALID_MASS", "The channel rate must be positive.")
    result = (Decimal(current) / rate).quantize(MASS_QUANTUM, rounding=ROUND_FLOOR)
    result = min(result, quantize_mass(max_mass))
    while result > 0 and calculate_buy_points(result, rate) > current:
        result -= MASS_QUANTUM
    return result


def max_sell_mass(balance: int, rate: Decimal, max_mass: Decimal) -> Decimal:
    if rate <= 0:
        raise EconomyDomainError("ECONOMY_INVALID_MASS", "The channel rate must be positive.")
    available = Decimal(provider_headroom(balance)) / rate
    result = min(quantize_mass(max_mass), available.quantize(MASS_QUANTUM, rounding=ROUND_FLOOR))
    while result > 0 and calculate_sell_points(result, rate) > provider_headroom(balance):
        result -= MASS_QUANTUM
    return result
