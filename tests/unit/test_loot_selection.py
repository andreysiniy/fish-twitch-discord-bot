"""Shared loot-table selection semantics used by both drop paths.

The fishing engine and the lootbox use-item path must resolve the same table
with the same selector: exhausted finite-stock entries never distort the
denominator and never win the roll, quantity is rolled inside the entry bounds,
and rarity luck only shifts weight (it never changes eligibility).
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from domain.logic.loot_selection import ItemDropResolution, select_item_drop
from services.loot_table_service import LootTableRollService


def _candidate(
    item_id="rod",
    weight=10,
    rarity="common",
    min_quantity=1,
    max_quantity=1,
    remaining_stock=None,
) -> dict:
    candidate = {
        "item_id": item_id,
        "title": item_id,
        "weight": weight,
        "rarity": rarity,
        "min_quantity": min_quantity,
        "max_quantity": max_quantity,
    }
    if remaining_stock is not None:
        candidate["remaining_stock"] = remaining_stock
    return candidate


def test_exhausted_entries_are_excluded_before_denominator() -> None:
    pool = [
        _candidate(item_id="heavy", weight=100, remaining_stock=0),
        _candidate(item_id="only", weight=1, remaining_stock=5),
    ]
    resolution = select_item_drop(pool, random_source=lambda: 0.0)
    assert resolution is not None
    assert resolution.item_id == "only"
    # The denominator excludes the exhausted entry; only the live weight counts.
    assert resolution.total_weight == Decimal("1")


def test_returns_none_when_every_entry_is_exhausted() -> None:
    pool = [
        _candidate(item_id="a", remaining_stock=0),
        _candidate(item_id="b", remaining_stock=0),
    ]
    assert select_item_drop(pool, random_source=lambda: 0.0) is None


def test_unlimited_entries_are_never_excluded() -> None:
    pool = [
        _candidate(item_id="unlimited"),
        _candidate(item_id="gone", remaining_stock=0),
    ]
    resolution = select_item_drop(pool, random_source=lambda: 0.0)
    assert resolution is not None
    assert resolution.item_id == "unlimited"


def test_quantity_is_rolled_inside_entry_bounds() -> None:
    calls = iter([0.0, 0.5])
    resolution = select_item_drop(
        [_candidate(item_id="bait", weight=1, min_quantity=2, max_quantity=5)],
        random_source=lambda: next(calls),
    )
    assert resolution is not None
    assert resolution.quantity_rolled == 4
    assert resolution.quantity_requested == 4


def test_rarity_luck_shifts_weight_toward_higher_rarities() -> None:
    pool = [
        _candidate(item_id="common", weight=10, rarity="common"),
        _candidate(item_id="legendary", weight=1, rarity="legendary"),
    ]
    neutral = select_item_drop(pool, rarity_luck=Decimal("1"), random_source=lambda: 0.5)
    lucky = select_item_drop(pool, rarity_luck=Decimal("10"), random_source=lambda: 0.5)
    assert neutral is not None and lucky is not None
    # neutral (10 vs 1): a 0.5 roll lands in the common bucket (scaled 5.5 < 10).
    assert neutral.item_id == "common"
    # lucky: legendary weight 1*10^3 vs common 10 => legendary dominates.
    assert lucky.item_id == "legendary"
    assert lucky.selection_probability > Decimal("0.9")


def test_service_entrypoint_uses_the_same_stock_aware_selector() -> None:
    pool = [
        _candidate(item_id="sold_out", weight=100, remaining_stock=0),
        _candidate(item_id="available", weight=1, remaining_stock=2),
    ]

    resolution = LootTableRollService.select(pool, random_source=lambda: 0.0)

    assert resolution is not None
    assert resolution.item_id == "available"


def test_legacy_rarity_filter_is_ignored_by_the_shared_selector() -> None:
    pool = [
        {
            **_candidate(item_id="common", weight=100, rarity="common"),
            "rarity_filter": "rare",
        },
        {
            **_candidate(item_id="rare", weight=1, rarity="rare"),
            "rarity_filter": "rare,legendary",
        },
    ]

    resolution = LootTableRollService.select(pool, random_source=lambda: 0.0)

    assert resolution is not None
    # The legacy field is no longer part of loot selection semantics.
    assert resolution.item_id == "common"


def test_delivery_policy_is_shared_by_fishing_and_lootbox() -> None:
    service = LootTableRollService.__new__(LootTableRollService)
    user = SimpleNamespace(id=1, channel_id=2)
    inventory = Mock()
    inventory.grant_many.return_value = [SimpleNamespace(slot_id=4, quantity=2)]
    overflow = Mock()
    resolution = ItemDropResolution(
        item_id="bait",
        item_definition_id=9,
        quantity_granted=2,
        status="selected",
    )

    resolved, rows = service.deliver(
        user,
        resolution,
        inventory_repo=inventory,
        overflow_repo=overflow,
        source_type="lootbox",
        source_id="use-1",
    )

    assert rows[0].slot_id == 4
    assert resolved.status == "granted"
    assert resolved.delivery_target == "inventory"
    assert resolved.inventory_grants == [{"slot_id": 4, "quantity": 2}]
    overflow.park.assert_not_called()


def test_multi_roll_reservation_refreshes_finite_stock() -> None:
    service = LootTableRollService.__new__(LootTableRollService)
    service.resolve_candidates = Mock(
        return_value=[
            {
                **_candidate(item_id="finite", weight=1, remaining_stock=1),
                "loot_table_entry_id": 7,
                "item_definition_id": 9,
            }
        ]
    )
    service.reserve = Mock(side_effect=lambda resolution: resolution.model_copy(
        update={
            "stock_before": 1,
            "stock_after": 0,
            "quantity_granted": 1,
        }
    ))

    # The second roll sees stock=0 and therefore produces no resolution.
    resolutions = service.roll(1, "table", rolls=2, random_source=lambda: 0.0)

    assert len(resolutions) == 1
    assert resolutions[0].quantity_granted == 1
