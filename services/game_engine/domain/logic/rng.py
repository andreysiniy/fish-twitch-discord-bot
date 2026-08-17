import random
from decimal import Decimal
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

RARITY_RANK = {
    "common": 0,
    "rare": 1,
    "epic": 2,
    "legendary": 3,
}

MIN_SAFE_LUCK = Decimal("0.05")


class WeightedRollResult(BaseModel):
    """Result of a weighted roll with enough detail to explain the outcome later."""

    selected: Optional[dict] = None
    selected_id: Optional[Any] = None
    roll: Decimal = Field(default_factory=lambda: Decimal("0"))
    total_weight: Decimal = Field(default_factory=lambda: Decimal("0"))
    selected_weight: Decimal = Field(default_factory=lambda: Decimal("0"))
    selected_probability: Decimal = Field(default_factory=lambda: Decimal("0"))
    candidate_count: int = 0

    def as_dict(self) -> dict:
        return {
            "selected_id": self.selected_id,
            "roll": str(self.roll),
            "total_weight": str(self.total_weight),
            "selected_weight": str(self.selected_weight),
            "selected_probability": str(self.selected_probability),
            "candidate_count": self.candidate_count,
            "selected": self.selected,
        }


def _to_decimal(value: Any) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception:
        return Decimal("0")


def _rarity_luck_weight(entry: dict, luck: float) -> Decimal:
    """Legacy luck-based weight shift preserved for the old wrapper."""
    weight = _to_decimal(entry.get("weight", 0))
    rarity_rank = RARITY_RANK.get(str(entry.get("rarity", "common")).lower(), 0)
    safe_luck = max(float(luck), float(MIN_SAFE_LUCK))
    return weight * _to_decimal(str(safe_luck**rarity_rank))


def _default_entry_weight(entry: dict) -> Decimal:
    return _to_decimal(entry.get("weight", 0))


def roll_loot_traced(
    loot_table: list[dict],
    weight_transform: Optional[Callable[[dict], Decimal]] = None,
    random_source: Callable[[], float] = random.random,
) -> WeightedRollResult:
    """Perform a deterministic weighted roll and return a traced result.

    `weight_transform` maps each candidate to its roll weight. `random_source`
    must return a float in ``[0, 1)``; the same value always selects the same
    candidate, which lets callers replay and explain any outcome.
    """
    entries: list[dict] = list(loot_table or [])
    if not entries:
        return WeightedRollResult(candidate_count=0)

    if weight_transform is None:
        def _default_weight(entry: dict) -> Decimal:
            return _to_decimal(entry.get("weight", 0))

        weight_transform = _default_weight

    weights = [_to_decimal(weight_transform(entry)) for entry in entries]
    total_weight = sum(weights, Decimal("0"))
    if total_weight <= 0:
        return WeightedRollResult(candidate_count=len(entries))

    raw_roll = max(_to_decimal(str(random_source())), Decimal("0"))
    scaled = (raw_roll * total_weight).quantize(Decimal("1e-6"))
    cumulative = Decimal("0")
    selected_idx = -1
    for idx, weight in enumerate(weights):
        cumulative += weight
        if scaled < cumulative:
            selected_idx = idx
            break

    if selected_idx == -1:
        selected_idx = len(entries) - 1

    selected = entries[selected_idx]
    selected_weight = weights[selected_idx]
    probability = (selected_weight / total_weight).quantize(Decimal("1e-12"))
    return WeightedRollResult(
        selected=selected,
        selected_id=_entry_id(selected),
        roll=scaled,
        total_weight=total_weight,
        selected_weight=selected_weight,
        selected_probability=probability,
        candidate_count=len(entries),
    )


def _entry_id(entry: dict) -> Any:
    if "reward_id" in entry:
        return entry["reward_id"]
    if "identifier" in entry:
        return entry["identifier"]
    if "id" in entry:
        return entry["id"]
    if "item_id" in entry:
        return entry["item_id"]
    return None


def roll_loot(
    loot_table: list[dict],
    luck_modifier: float = 1.0,
    random_source: Callable[[], float] = random.random,
):
    """Legacy weighted pick; kept as a thin wrapper over the traced roll.

    A luck modifier shifts weight toward higher rarities for backward
    compatibility with existing callers. New code should prefer
    ``roll_loot_traced`` and explicit weight transforms.
    """
    result = roll_loot_traced(
        loot_table,
        weight_transform=lambda entry: _rarity_luck_weight(entry, luck_modifier),
        random_source=random_source,
    )
    return result.selected


def calculate_chance_traced(
    chance: float,
    random_source: Callable[[], float] = random.random,
) -> tuple[bool, Decimal]:
    """Chance roll that also returns the raw roll value for traceability."""
    roll = Decimal(str(max(random_source(), 0.0)))
    return roll < _to_decimal(chance), roll


def is_russian_roulette_hit_traced(
    bullets: int,
    chambers: int,
    random_source: Callable[[], float] = random.random,
) -> tuple[bool, Decimal]:
    if chambers <= 0:
        return False, Decimal("0")
    return calculate_chance_traced(bullets / chambers, random_source=random_source)
