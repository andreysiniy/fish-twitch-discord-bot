"""Unified loot-table roll service shared by the fishing and lootbox paths.

Both drop sources must resolve one table with one selector and one stock
reservation policy. This service owns the database-facing orchestration and
returns typed ``ItemDropResolution`` objects that callers (and the cast
ledger) can reuse without re-deriving weights or rolls.
"""

import random
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy.orm import Session

from domain.logic.loot_selection import ItemDropResolution, select_item_drop
from infrastructure.models import LootTable, LootTableEntry


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
        rarity_luck: Decimal = Decimal("1"),
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
        rarity_luck: Decimal = Decimal("1"),
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
            resolutions.append(self.reserve(resolution))
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
