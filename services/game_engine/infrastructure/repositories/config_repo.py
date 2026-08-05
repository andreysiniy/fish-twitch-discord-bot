from sqlalchemy import or_
from sqlalchemy.orm import Session

from infrastructure.models import (
    Channel,
    LootTableEntry,
    LootTableEntryStock,
    LocationItem,
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
            return [self._serialize_loot_table_entry(entry) for entry in entries]
        db_items = self.db.query(LocationItem).filter(
            LocationItem.reward_pool_id == pool_obj.id,
            or_(LocationItem.quantity.is_(None), LocationItem.quantity > 0)
        ).all()
        return [self._serialize_location_item(item) for item in db_items]

    def consume_item_stock(self, item: dict, amount: int = 1) -> bool:
        """Consume stock for a drop candidate regardless of its source.

        Returns whether the grant may proceed. Loot-table entries use the global
        stock table; legacy location rows use their in-line quantity.
        """
        if amount <= 0:
            return True
        source = item.get("_source")
        if source == "loot_table":
            return self.consume_loot_table_entry_stock(item.get("db_id"), amount=amount)
        location_item_id = item.get("db_id")
        if not location_item_id:
            return True
        return self.consume_location_item_stock(location_item_id, amount=amount)

    def consume_location_item_stock(self, location_item_id: int, amount: int = 1) -> bool:
        if amount <= 0:
            return True

        db_item = (
            self.db.query(LocationItem)
            .filter(LocationItem.id == location_item_id)
            .with_for_update(of=LocationItem)
            .first()
        )
        if not db_item:
            return False

        if db_item.quantity is None:
            return True

        if int(db_item.quantity) < amount:
            return False
        db_item.quantity = int(db_item.quantity) - amount
        db_item.version += 1
        self.db.flush()
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
            "message": entry.message or "You caught {name}!",
            "effects": definition.effects or [],
            "definition_version": definition.version,
            "loot_table_id": entry.loot_table_id,
            "loot_table_entry_id": entry.id,
        }

    def _serialize_location_item(self, item: LocationItem) -> dict:
        definition = item.definition
        logical_item_id = definition.item_id if definition else item.item_id
        title = definition.title if definition else logical_item_id
        if not definition:
            raise ValueError(f"Location item {item.id} has no definition")

        return {
            "db_id": item.id,
            "item_id": logical_item_id,
            "title": title,
            "description": definition.description if definition else None,
            "image_url": definition.image_url if definition else None,
            "rarity": definition.rarity if definition else "common",
            "item_type": definition.type,
            "equipment_slot": definition.slot,
            "max_durability": definition.max_durability,
            "break_policy": definition.break_policy,
            "stack_size": definition.stack_size if definition else 1,
            "weight": item.weight,
            "xp_gain": item.xp_gain,
            "quantity": item.quantity,
            "message": item.message,
            "effects": definition.effects or [],
            "definition_version": definition.version,
        }
