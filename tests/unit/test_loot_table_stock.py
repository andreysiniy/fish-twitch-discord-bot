
from infrastructure.database import Base
from infrastructure.models import LootTableEntry, RewardPool


def test_loot_table_entry_stock_model_columns() -> None:
    table = Base.metadata.tables["loot_table_entry_stock"]
    columns = {column.name: column for column in table.columns}
    assert {"id", "loot_table_entry_id", "remaining_quantity", "version", "updated_at"} <= set(
        columns
    )
    fk = next(
        (fk for fk in table.foreign_keys if fk.target_fullname == "loot_table_entries.id"),
        None,
    )
    assert fk is not None


def test_loot_table_entry_has_stock_relationship() -> None:
    entry = LootTableEntry()
    assert hasattr(entry, "stock")


def test_reward_pool_has_item_loot_table_link() -> None:
    pool = RewardPool(channel_id=1, location_id="x")
    assert pool.item_loot_table_id is None
