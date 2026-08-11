"""Pure economy parsing and pricing rules.

The game engine owns these rules so Twitch, Discord and internal workers all
interpret mass arguments and point transfers identically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation


MASS_QUANTUM = Decimal("0.01")
MAX_MASS_INPUT = Decimal("1E24")

_MASS_PATTERN = re.compile(
    r"^(?P<amount>(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+))(?P<unit>kg|t|kt|mt|gt)?$"
)
MASS_UNIT_MULTIPLIERS: dict[str | None, Decimal] = {
    None: Decimal("1"),
    "kg": Decimal("1"),
    "t": Decimal("1000"),
    "kt": Decimal("1000000"),
    "mt": Decimal("1000000000"),
    "gt": Decimal("1000000000000"),
}


class EconomyDomainError(ValueError):
    """A stable domain error which can be mapped to an API error code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ParsedMassArgument:
    raw: str
    mode: str
    unit: str | None
    multiplier_kg: Decimal
    mass_kg: Decimal | None


def parse_mass_argument(raw: str | None, *, allow_all: bool = True) -> ParsedMassArgument:
    """Parse the canonical Twitch/Discord mass grammar using :class:`Decimal`.

    ``all`` is represented explicitly and is resolved by the calling use case
    against a locked balance/mass snapshot.  It is intentionally not treated
    as a numeric alias.
    """

    normalized = str(raw or "").strip().lower()
    if allow_all and normalized == "all":
        return ParsedMassArgument("all", "all", None, Decimal("1"), None)
    if not normalized or normalized == "all":
        raise EconomyDomainError(
            "ECONOMY_INVALID_MASS", "Enter a positive mass such as 5kg or 1.5t."
        )

    match = _MASS_PATTERN.fullmatch(normalized)
    if not match:
        raise EconomyDomainError(
            "ECONOMY_INVALID_MASS",
            "Invalid mass. Use a positive number with kg, t, kt, mt, gt, or all.",
        )
    unit = match.group("unit")
    multiplier = MASS_UNIT_MULTIPLIERS[unit]
    try:
        amount = Decimal(match.group("amount"))
    except InvalidOperation as error:  # pragma: no cover - regex already constrains input
        raise EconomyDomainError("ECONOMY_INVALID_MASS", "Invalid mass.") from error
    if not amount.is_finite() or amount <= 0:
        raise EconomyDomainError("ECONOMY_INVALID_MASS", "Mass must be a positive finite number.")
    if amount > MAX_MASS_INPUT / multiplier:
        raise EconomyDomainError("ECONOMY_INVALID_MASS", "Mass is too large.")
    mass = (amount * multiplier).quantize(MASS_QUANTUM)
    if mass <= 0 or mass > MAX_MASS_INPUT:
        raise EconomyDomainError("ECONOMY_INVALID_MASS", "Mass is outside the supported range.")
    return ParsedMassArgument(normalized, "exact", unit, multiplier, mass)


def quantize_mass(value: Decimal | int | str) -> Decimal:
    """Quantize mass at the single defined boundary."""

    try:
        result = Decimal(str(value)).quantize(MASS_QUANTUM)
    except (InvalidOperation, ValueError) as error:
        raise EconomyDomainError("ECONOMY_INVALID_MASS", "Invalid mass.") from error
    if not result.is_finite():
        raise EconomyDomainError("ECONOMY_INVALID_MASS", "Mass must be finite.")
    return result


def calculate_buy_points(mass_kg: Decimal, rate_points_per_kg: Decimal) -> int:
    mass = quantize_mass(mass_kg)
    rate = Decimal(str(rate_points_per_kg))
    if mass <= 0 or rate <= 0:
        raise EconomyDomainError("ECONOMY_INVALID_MASS", "Mass and rate must be positive.")
    return int((mass * rate).to_integral_value(rounding=ROUND_CEILING))


def calculate_sell_points(mass_kg: Decimal, rate_points_per_kg: Decimal) -> int:
    mass = quantize_mass(mass_kg)
    rate = Decimal(str(rate_points_per_kg))
    if mass <= 0 or rate <= 0:
        raise EconomyDomainError("ECONOMY_INVALID_MASS", "Mass and rate must be positive.")
    return int((mass * rate).to_integral_value(rounding=ROUND_FLOOR))
