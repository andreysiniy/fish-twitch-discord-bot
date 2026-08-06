from sqlalchemy.orm import Session

from infrastructure.models import (
    Channel,
    LootTableEntry,
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
        """Resolve drop candidates from the unified loot table, else legacy rows."""
        if pool_obj.item_loot_table_id is not None:
            entries = (
                self.db.query(LootTableEntry)
                .filter(
                    LootTableEntry.loot_table_id == pool_obj.item_loot_table_id,
                    LootTableEntry.item_definition_id.isnot(None),
                )
                .all()
            )
            return [
                self._serialize_loot_table_entry(entry)
                for entry in entries
                if self._matches_rarity_filter(entry, pool_obj)
            ]
        # No unified loot table: the location has no item drops.
        return []

    @staticmethod
    def _matches_rarity_filter(entry: LootTableEntry, pool_obj: RewardPool) -> bool:
        """Apply an entry rarity gate against the current player context.

        ``rarity_filter`` is a comma-separated list of accepted rarities
        (e.g. ``"epic,legendary"``). An empty or null filter accepts every
        entry. The definition's rarity is the only stable rarity source.
        """
        if not entry.rarity_filter:
            return True
        allowed = {
            part.strip().lower()
            for part in entry.rarity_filter.split(",")
            if part.strip()
        }
        if not allowed:
            return True
        return str((entry.definition.rarity or "").lower()) in allowed

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
        stock = (
            self.db.query(LootTableEntryStock)
            .filter(LootTableEntryStock.loot_table_entry_id == entry_id)
            .with_for_update(of=LootTableEntryStock)
            .first()
        )
        if stock is None:
            return True
        if int(stock.remaining_quantity) < amount:
            return False
        stock.remaining_quantity = int(stock.remaining_quantity) - amount
        stock.version += 1
        self.db.flush()
        return True

    def _serialize_loot_table_entry(self, entry: LootTableEntry) -> dict:
        definition = entry.definition
        return {
            "_source": "loot_table",
            "db_id": entry.id,
            "item_id": definition.item_id,
            "title": definition.title,
            "description": definition.description,
            "image_url": definition.image_url,
            "rarity": definition.rarity,
            "item_type": definition.type,
            "equipment_slot": definition.slot,
            "max_durability": definition.max_durability,
            "break_policy": definition.break_policy,
            "stack_size": definition.stack_size,
            "weight": entry.weight,
            "xp_gain": entry.xp_gain,
            "quantity": None,
            "min_quantity": entry.min_quantity,
            "max_quantity": entry.max_quantity,
            "rarity_filter": entry.rarity_filter,
            "message": entry.message or "You caught {name}!",
            "effects": definition.effects or [],
            "definition_version": definition.version,
            "item_definition_id": entry.item_definition_id,
            "loot_table_id": entry.loot_table_id,
            "loot_table_entry_id": entry.id,
        }

