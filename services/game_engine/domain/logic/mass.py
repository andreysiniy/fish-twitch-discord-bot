from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

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


def apply_mass_mutation(
    holder: Any,
    requested_delta: object,
    *,
    mass_floor: object = ZERO_MASS,
    track_total: bool = True,
) -> Decimal:
    """Apply a mass delta through the shared invariants.

    The delta is quantized once, the result is clamped at ``mass_floor``, and
    the positive applied portion is added to ``total_mass_stat`` when
    ``track_total`` is set. Returns the applied delta (the amount that actually
    landed) so callers can report or ledger it.
    """
    previous_mass = quantize_mass(holder.current_mass)
    floor = max(quantize_mass(mass_floor), ZERO_MASS)
    new_mass = max(quantize_mass(previous_mass + to_decimal(requested_delta)), floor)
    applied = quantize_mass(new_mass - previous_mass)
    holder.current_mass = new_mass
    if track_total and applied > ZERO_MASS:
        holder.total_mass_stat = quantize_mass(to_decimal(holder.total_mass_stat) + applied)
    return applied
