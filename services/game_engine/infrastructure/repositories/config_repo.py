from sqlalchemy.orm import Session

from infrastructure.models import (
    Channel,
    LootTableEntryStock,
    RewardPool,
)


class ConfigRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_locations(self, channel_twitch_id: str) -> list[RewardPool]:
        return (
            self.db.query(RewardPool)
            .join(Channel)
            .filter(Channel.twitch_id == channel_twitch_id)
            .order_by(RewardPool.location_id.asc())
            .all()
        )

    def get_dual_pool(self, channel_twitch_id: str, location_id: str):
        """
        Returns:
        1. Rewards list (from JSON)
        2. Items list (from DB)
        3. Item drop rate (float)
        """
        pool_obj = (
            self.db.query(RewardPool)
            .join(Channel)
            .filter(Channel.twitch_id == channel_twitch_id)
            .filter(RewardPool.location_id == location_id)
            .first()
        )

        if not pool_obj:
            return [{"type": "nothing", "weight": 100, "message": "No fish here..."}], [], 0.0

        rewards = list(pool_obj.rewards_data)
        if not rewards:
            rewards = [{"type": "nothing", "weight": 100, "message": "No fish here..."}]

        items = self._resolve_item_entries(pool_obj)
        return rewards, items, pool_obj.items_drop_rate

    def _resolve_item_entries(self, pool_obj: RewardPool) -> list[dict]:
        """Resolve fishing candidates through the canonical loot-table API."""
        if pool_obj.item_loot_table_id is None:
            return []
        from services.loot_table_service import LootTableRollService

        return LootTableRollService(self.db).resolve_candidates(
            pool_obj.channel_id,
            pool_obj.item_loot_table_id,
            allow_missing=True,
        )

    def consume_item_stock(self, item: dict, amount: int = 1) -> bool:
        """Consume stock for a drop candidate.

        Only unified loot-table entries carry stock; the legacy location path
        was removed in migration 20260802_0022.
        """
        if amount <= 0:
            return True
        source = item.get("_source")
        if source == "loot_table":
            return self.consume_loot_table_entry_stock(item.get("db_id"), amount=amount)
        return True

    def consume_loot_table_entry_stock(self, entry_id: int | None, amount: int = 1) -> bool:
        """Atomically consume global stock for a loot-table entry.

        An entry with no stock row is unlimited. Returns whether the grant may
        proceed; stock exhaustion is reported, never silently fabricated.
        """
        if amount <= 0 or entry_id is None:
            return True
        stock = self._lock_stock_row(entry_id)
        if stock is None:
            return True
        if int(stock.remaining_quantity) < amount:
            return False
        stock.remaining_quantity = int(stock.remaining_quantity) - amount
        stock.version += 1
        self.db.flush()
        return True

    def reserve_loot_table_entry_stock(
        self, entry_id: int | None, quantity_requested: int
    ) -> tuple[bool, int | None, int | None, int]:
        """Reserve exactly ``quantity_requested`` stock for one drop.

        Returns ``(ok, stock_before, stock_after, reserved)``. Unlimited
        entries reserve the full requested quantity. Finite stock clamps to
        what remains (``reserved < quantity_requested``) instead of failing the
        whole cast; ``ok`` is ``False`` only when the entry ran out entirely.
        """
        if quantity_requested <= 0 or entry_id is None:
            return True, None, None, quantity_requested
        stock = self._lock_stock_row(entry_id)
        if stock is None:
            return True, None, None, quantity_requested
        before = int(stock.remaining_quantity)
        if before <= 0:
            return False, before, before, 0
        reserved = min(before, quantity_requested)
        stock.remaining_quantity = before - reserved
        stock.version += 1
        self.db.flush()
        return True, before, before - reserved, reserved

    def _lock_stock_row(self, entry_id: int) -> LootTableEntryStock | None:
        return (
            self.db.query(LootTableEntryStock)
            .filter(LootTableEntryStock.loot_table_entry_id == entry_id)
            .with_for_update(of=LootTableEntryStock)
            .first()
        )
