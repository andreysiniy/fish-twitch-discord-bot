"""Shared loot-table item selection used by the fishing and lootbox paths.

Both drop sources must produce the same selection semantics for the same
table, RNG and context. This module owns the pure part of that contract:

- excludes ``remaining_stock == 0`` entries before the weighted roll;
- rolls the weighted entry (rarity luck is applied only where the caller has
  a fishing context, exactly like the old engine weight transform);
- rolls a quantity inside the entry's ``min_quantity``/``max_quantity``;
- returns one typed ``ItemDropResolution`` without touching the database.

The database-side stock reservation and delivery stay in the service layer;
``quantity_requested`` is always the rolled quantity so reservation can
reserve exactly what the selection produced.
"""

import random
from decimal import Decimal
from typing import Any, Callable

from pydantic import BaseModel, Field

from domain.logic import rng

MIN_SAFE_LUCK = Decimal("0.05")

SELECTED = "selected"
GATE_FAILED = "gate_failed"
NO_CANDIDATES = "no_candidates"


class ItemDropResolution(BaseModel):
    """Typed outcome of one loot-table selection, ready for ledger reuse."""

    loot_table_id: int | None = None
    loot_entry_id: int | None = None
    item_definition_id: int | None = None
    item_id: str = ""
    title: str = ""
    rarity: str | None = None
    item_type: str | None = None
    definition_version: int | None = None
    selected_weight: Decimal = Decimal("0")
    total_weight: Decimal = Decimal("0")
    selection_probability: Decimal = Decimal("0")
    selection_roll: Decimal = Decimal("0")
    min_quantity: int = 1
    max_quantity: int = 1
    quantity_rolled: int = 1
    quantity_requested: int = 1
    stock_before: int | None = None
    stock_after: int | None = None
    quantity_granted: int = 0
    inventory_grants: list[dict[str, Any]] = Field(default_factory=list)
    delivery_target: str | None = None
    status: str = SELECTED
    gate_success: bool | None = None
    selection_success: bool | None = None
    stock_reserved: bool | None = None
    failure_reason: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _is_out_of_stock(candidate: dict[str, Any]) -> bool:
    """True when the candidate is a finite-stock entry that is exhausted."""
    remaining = candidate.get("remaining_stock")
    if remaining is None:
        return False
    try:
        return int(remaining) == 0
    except (TypeError, ValueError):
        return False


def _matches_rarity_filter(candidate: dict[str, Any]) -> bool:
    """Apply the entry's explicit rarity filter in every runtime path."""
    raw_filter = candidate.get("rarity_filter")
    if not raw_filter:
        return True
    allowed = {
        part.strip().lower()
        for part in str(raw_filter).split(",")
        if part.strip()
    }
    if not allowed:
        return True
    return str(candidate.get("rarity", "")).lower() in allowed


def _rarity_luck_weight(entry: dict[str, Any], luck: Decimal) -> Decimal:
    """Rarity luck shifts weight toward higher rarities (fishing context)."""
    rarity_rank = rng.RARITY_RANK.get(str(entry.get("rarity", "common")).lower(), 0)
    safe_luck = max(luck, MIN_SAFE_LUCK)
    return rng._to_decimal(entry.get("weight", 0)) * (safe_luck**rarity_rank)


def _roll_quantity(
    candidate: dict[str, Any],
    random_source: Callable[[], float],
) -> int:
    """Roll a quantity inside the candidate's bounds using the same RNG source."""
    min_quantity = max(int(candidate.get("min_quantity") or 1), 1)
    max_quantity = max(int(candidate.get("max_quantity") or min_quantity), min_quantity)
    if max_quantity <= min_quantity:
        return min_quantity
    span = max_quantity - min_quantity + 1
    offset = int(random_source() * span)
    return min_quantity + min(offset, span - 1)


def select_item_drop(
    candidates: list[dict[str, Any]],
    rarity_luck: Decimal = Decimal("1"),
    random_source: Callable[[], float] = random.random,
) -> ItemDropResolution | None:
    """Select one entry from ``candidates`` with the shared fishing semantics.

    Exhausted finite-stock entries are excluded before the denominator is
    computed, so they neither distort probabilities nor win the roll. Returns
    ``None`` when no eligible candidate remains.
    """
    eligible = [
        candidate
        for candidate in candidates
        if not _is_out_of_stock(candidate) and _matches_rarity_filter(candidate)
    ]
    if not eligible:
        return None

    luck = Decimal(rarity_luck)
    trace = rng.roll_loot_traced(
        eligible,
        weight_transform=lambda entry: _rarity_luck_weight(entry, luck),
        random_source=random_source,
    )
    if trace.selected is None or trace.total_weight <= 0:
        return None

    entry = trace.selected
    quantity = _roll_quantity(entry, random_source)
    return ItemDropResolution(
        loot_table_id=entry.get("loot_table_id"),
        loot_entry_id=entry.get("loot_table_entry_id") or entry.get("db_id"),
        item_definition_id=entry.get("item_definition_id"),
        item_id=entry.get("item_id", ""),
        title=entry.get("title") or entry.get("item_id", "Unknown Item"),
        rarity=entry.get("rarity"),
        item_type=entry.get("item_type"),
        definition_version=entry.get("definition_version"),
        selected_weight=trace.selected_weight,
        total_weight=trace.total_weight,
        selection_probability=trace.selected_probability,
        selection_roll=trace.roll,
        min_quantity=max(int(entry.get("min_quantity") or 1), 1),
        max_quantity=max(int(entry.get("max_quantity") or 1), 1),
        quantity_rolled=quantity,
        quantity_requested=quantity,
        status=SELECTED,
        gate_success=True,
        selection_success=True,
        message=entry.get("message"),
        metadata=dict(entry),
    )
