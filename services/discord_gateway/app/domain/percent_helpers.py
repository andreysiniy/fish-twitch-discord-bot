"""Percent / ratio / probability conversion helpers (wizard spec §50).

Discord admin UIs deal in human units — ``10`` means ten percent — while the
backend item payload stores ratios such as ``0.10``. No item modal is allowed
to do its own ``/ 100`` or ``* 100``; everything flows through these helpers so
the unit boundary is defined in exactly one place.
"""

from decimal import Decimal

PERCENT_DIVISOR = Decimal(100)


def percent_to_ratio(value: Decimal) -> Decimal:
    """Convert a human percentage (``10``) to a backend ratio (``0.10``)."""
    return value / PERCENT_DIVISOR


def ratio_to_percent(value: Decimal) -> Decimal:
    """Convert a backend ratio (``0.10``) to a human percentage (``10``)."""
    return value * PERCENT_DIVISOR


def percentage_points_to_probability(value: Decimal) -> Decimal:
    """Convert percentage points (``0.5``) to an additive probability (``0.005``).

    Used for stats like ``item_drop_chance_add`` where ``0.5`` shifts a base
    chance of 6% to 6.5% (spec §17.1).
    """
    return value / PERCENT_DIVISOR


def probability_to_percentage_points(value: Decimal) -> Decimal:
    """Convert an additive probability (``0.005``) back to percentage points."""
    return value * PERCENT_DIVISOR
