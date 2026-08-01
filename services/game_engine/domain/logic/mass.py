from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MASS_QUANTUM = Decimal("0.01")
ZERO_MASS = Decimal("0.00")


def to_decimal(value: object) -> Decimal:
    if value is None or value == "":
        return ZERO_MASS
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Invalid decimal value") from error


def quantize_mass(value: object) -> Decimal:
    return to_decimal(value).quantize(MASS_QUANTUM, rounding=ROUND_HALF_UP)
