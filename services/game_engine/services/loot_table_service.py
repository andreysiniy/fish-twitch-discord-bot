"""Unified loot-table roll service shared by the fishing and lootbox paths.

Both drop sources must resolve one table with one selector and one stock
reservation policy. This service owns the database-facing orchestration and
returns typed ``ItemDropResolution`` objects that callers (and the cast
ledger) can reuse without re-deriving weights or rolls.
"""

import random
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from domain.logic.loot_selection import ItemDropResolution, select_item_drop
from infrastructure.models import LootTable, LootTableEntry
from sqlalchemy.orm import Session


class LootTableRollService:
    """Resolves loot-table entries with fishing semantics for any caller."""

    def __init__(self, db: Session):
        self.db = db
        # Import lazily: the repository package exports InventoryRepository,
        # which itself uses this service for lootbox delivery.
        from infrastructure.repositories.config_repo import ConfigRepository

        self.config_repo = ConfigRepository(db)

    @staticmethod
    def select(
        candidates: list[dict[str, Any]],
        *,
        rarity_luck: Decimal = Decimal(1),
        random_source: Callable[[], float] = random.random,
    ) -> ItemDropResolution | None:
        """Run the canonical pure selector for an already loaded table.

        Fishing and lootbox callers may have different transaction lifecycles,
        but they must not have different selection semantics. Keeping this
        entry point on the orchestration service makes that contract explicit.
        """
        return select_item_drop(
            candidates,
            rarity_luck=rarity_luck,
            random_source=random_source,
        )

    def resolve_candidates(self, channel_id: int, loot_table_id: str) -> list[dict[str, Any]]:
        """Load eligible entries with their stock; stock=0 stays for the selector."""
        from infrastructure.repositories.loot_table_serializer import (
            load_stock_by_entry,
            serialize_loot_table_entry,
        )

        table = (
            self.db.query(LootTable)
            .filter(
                LootTable.channel_id == channel_id,
                LootTable.table_id == loot_table_id,
                LootTable.is_active.is_(True),
            )
            .first()
        )
        if not table:
            raise ValueError(f"Active loot table '{loot_table_id}' not found")
        entries = (
            self.db.query(LootTableEntry)
            .filter(LootTableEntry.loot_table_id == table.id)
            .order_by(LootTableEntry.id.asc())
            .all()
        )
        if not entries:
            raise ValueError(f"Loot table '{loot_table_id}' is empty")
        stock_by_entry = load_stock_by_entry(self.db, entries)
        return [
            serialize_loot_table_entry(entry, stock_by_entry.get(entry.id)) for entry in entries
        ]

    def roll(
        self,
        channel_id: int,
        loot_table_id: str,
        rolls: int = 1,
        rarity_luck: Decimal = Decimal(1),
        random_source: Callable[[], float] = random.random,
    ) -> list[ItemDropResolution]:
        """Select and reserve one entry per roll with the shared policy."""
        candidates = self.resolve_candidates(channel_id, loot_table_id)
        resolutions: list[ItemDropResolution] = []
        for _ in range(rolls):
            resolution = self.select(
                candidates, rarity_luck=rarity_luck, random_source=random_source
            )
            if resolution is None:
                continue
            reserved = self.reserve(resolution)
            resolutions.append(reserved)
            # A multi-roll lootbox must use the stock state produced by the
            # previous reservation; otherwise one stale snapshot could select
            # the same finite entry repeatedly in a single use.
            if reserved.loot_entry_id is not None and reserved.stock_after is not None:
                for candidate in candidates:
                    candidate_entry_id = candidate.get("loot_table_entry_id") or candidate.get(
                        "db_id"
                    )
                    if candidate_entry_id == reserved.loot_entry_id:
                        candidate["remaining_stock"] = reserved.stock_after
                        break
        return resolutions

    def reserve(self, resolution: ItemDropResolution) -> ItemDropResolution:
        """Reserve the selected quantity, clamping to remaining stock."""
        ok, before, after, reserved = self.config_repo.reserve_loot_table_entry_stock(
            resolution.loot_entry_id, resolution.quantity_requested
        )
        if not ok:
            resolution.status = "stock_empty"
            resolution.failure_reason = "entry stock exhausted"
        resolution.stock_before = before
        resolution.stock_after = after
        resolution.quantity_requested = resolution.quantity_rolled
        resolution.quantity_granted = reserved if ok else 0
        return resolution

    def deliver(
        self,
        user: Any,
        resolution: ItemDropResolution,
        *,
        inventory_repo: Any,
        overflow_repo: Any,
        source_type: str,
        source_id: str | None,
        grant_overrides: dict[str, Any] | None = None,
    ) -> tuple[ItemDropResolution, list[Any]]:
        """Deliver a reserved drop to inventory or durable overflow storage.

        Fishing and lootbox use the same delivery policy: a stock reservation
        is never lost when inventory is full, and a failed durable delivery is
        explicit in the typed resolution.  ``InventoryCapacityError`` is
        imported lazily to keep the service independent from the repository
        that delegates to it.
        """
        quantity = int(resolution.quantity_granted or 0)
        if resolution.status == "stock_empty" or quantity <= 0:
            return resolution, []

        from infrastructure.repositories.inventory_repo import InventoryCapacityError

        grant = {"item_id": resolution.item_id, "quantity": quantity}
        if grant_overrides:
            grant.update(grant_overrides)
        try:
            rows = inventory_repo.grant_many(user, [grant])
        except InventoryCapacityError:
            if resolution.item_definition_id is None:
                resolution.status = "failed"
                resolution.failure_reason = "item definition is unavailable"
                resolution.quantity_granted = 0
                return resolution, []
            overflow_repo.park(
                user=user,
                item_definition_id=resolution.item_definition_id,
                quantity=quantity,
                source_type=source_type,
                source_id=source_id,
            )
            resolution.status = "overflowed"
            resolution.delivery_target = "overflow"
            resolution.inventory_grants = []
            return resolution, []

        resolution.status = "granted"
        resolution.delivery_target = "inventory"
        resolution.inventory_grants = [
            {"slot_id": row.slot_id, "quantity": row.quantity} for row in rows
        ]
        return resolution, rows
