"""Canonical action classification for behavioral item effects."""

from decimal import Decimal, InvalidOperation
from typing import Any

CANONICAL_OUTCOME_TYPES = frozenset(
    {
        "nothing",
        "fish_positive",
        "fish_negative",
        "fish_zero",
        "robbery",
        "timeout",
        "russian_roulette",
        "dupe",
    }
)

LEGACY_OUTCOME_ALIASES = {
    "negative_mass": "fish_negative",
    "negative_percentage": "fish_negative",
    "positive_mass": "fish_positive",
    "positive_percentage": "fish_positive",
}


def normalize_outcome_target(value: str) -> str:
    normalized = LEGACY_OUTCOME_ALIASES.get(str(value or "").strip().lower(), str(value or "").strip().lower())
    if normalized not in CANONICAL_OUTCOME_TYPES:
        raise ValueError(f"Unknown outcome target: {value}")
    return normalized


def classify_outcome(outcome: dict[str, Any] | None) -> str:
    """Classify a rolled reward without duplicating reward selection logic."""
    if not isinstance(outcome, dict):
        return "nothing"
    outcome_type = str(outcome.get("type") or "nothing").strip().lower()
    if outcome_type != "fish":
        return LEGACY_OUTCOME_ALIASES.get(outcome_type, outcome_type)

    values: list[Decimal] = []
    for key in ("fixed_mass", "mass", "percentage"):
        if outcome.get(key) is None:
            continue
        try:
            values.append(Decimal(str(outcome[key])))
        except (InvalidOperation, TypeError, ValueError):
            return "fish_zero"
    if not values:
        for key in ("min_mass", "max_mass"):
            if outcome.get(key) is not None:
                try:
                    values.append(Decimal(str(outcome[key])))
                except (InvalidOperation, TypeError, ValueError):
                    return "fish_zero"
    if not values or all(value == 0 for value in values):
        return "fish_zero"
    if all(value < 0 for value in values):
        return "fish_negative"
    if all(value >= 0 for value in values):
        return "fish_positive"
    return "fish_positive"
