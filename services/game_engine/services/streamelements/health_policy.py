"""Shared StreamElements health scheduling policy."""

from __future__ import annotations

import random
from collections.abc import Callable


def backoff_seconds(
    failures: int, *, rng: Callable[[float, float], float] = random.uniform
) -> float:
    """Return the transient-failure retry delay with the required jitter."""

    normalized = max(failures, 1)
    base = 1800 if normalized >= 5 else {1: 60, 2: 120, 3: 300, 4: 900}[normalized]
    return base * rng(0.9, 1.1)


def regular_interval_seconds(
    *, rng: Callable[[float, float], float] = random.uniform
) -> float:
    """Return the regular 30-minute validation interval with jitter."""

    return 1800 * rng(0.9, 1.1)
