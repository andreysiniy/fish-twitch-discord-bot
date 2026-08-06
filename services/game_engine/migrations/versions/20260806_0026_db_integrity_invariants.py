"""Database integrity invariants from the compliance review.

- reward_pools -> loot_tables becomes a tenant-aware composite FK
  (item_loot_table_id, channel_id) -> loot_tables(id, channel_id) so a pool of
  channel A can never reference a loot table of channel B (RESTRICT on delete).
- loot_table_entry_stock gets a UNIQUE index on loot_table_entry_id: the ORM
  declared a one-to-one stock row but the database allowed duplicates.
- inventory_item_use_records.inventory_item_id gets a real FK (CASCADE).
- reward_pools.items_drop_rate moves from binary float to NUMERIC(18,6).
- CHECK constraints cover event status/version, loot table version, entry
  version/config_version and stock version.

pgcrypto is intentionally NOT dropped here: migration 0002 creates the
extension and the older ledger migrations still reference gen_random_uuid;
production keeps managing extensions at the infrastructure level, while the
runtime no longer depends on pgcrypto for new rows (native UUID columns).

Revision ID: 20260806_0026
Revises: 20260806_0025
"""

from alembic import op
import sqlalchemy as sa

revision = "20260806_0026"
down_revision = "20260806_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Tenant-aware pool -> loot table FK.
    op.drop_constraint(
        "reward_pools_item_loot_table_id_fkey",
        "reward_pools",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_reward_pools_item_loot_table_channel",
        "reward_pools",
        "loot_tables",
        ["item_loot_table_id", "channel_id"],
        ["id", "channel_id"],
        ondelete="RESTRICT",
    )

    # 2. One stock row per loot-table entry.
    op.drop_index(
        "ix_loot_table_entry_stock_loot_table_entry_id",
        table_name="loot_table_entry_stock",
    )
    op.create_unique_constraint(
        "uq_loot_table_entry_stock_loot_table_entry_id",
        "loot_table_entry_stock",
        ["loot_table_entry_id"],
    )

    # 2b. Restore the single-column FK that the model still declares on
    # equipped_items.inventory_item_id (migration 0008 dropped it); without it
    # the ORM relationship join is ambiguous with the composite FK.
    op.create_foreign_key(
        "fk_equipped_items_inventory_item_id_inventory_items",
        "equipped_items",
        "inventory_items",
        ["inventory_item_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 3. Real FK for item use records.
    op.alter_column(
        "inventory_item_use_records",
        "inventory_item_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_inventory_item_use_records_inventory_item_id_inventory_items",
        "inventory_item_use_records",
        "inventory_items",
        ["inventory_item_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 4. items_drop_rate as NUMERIC instead of binary float.
    op.alter_column(
        "reward_pools",
        "items_drop_rate",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 6),
        existing_nullable=False,
        existing_server_default=sa.text("0.1"),
    )

    # 5. CHECK constraints for versioned/status state.
    op.create_check_constraint(
        "ck_fishing_events_status_values",
        "fishing_events",
        "status IN ('draft', 'active', 'ended')",
    )
    op.create_check_constraint(
        "ck_fishing_events_version_positive",
        "fishing_events",
        "version >= 1",
    )
    op.create_check_constraint(
        "ck_fishing_events_modifier_schema_version_positive",
        "fishing_events",
        "modifier_schema_version >= 1",
    )
    op.create_check_constraint(
        "ck_loot_tables_version_positive",
        "loot_tables",
        "version >= 1",
    )
    op.create_check_constraint(
        "ck_loot_table_entries_version_positive",
        "loot_table_entries",
        "version >= 1",
    )
    op.create_check_constraint(
        "ck_loot_table_entries_config_version_positive",
        "loot_table_entries",
        "config_version >= 1",
    )
    op.create_check_constraint(
        "ck_loot_table_entry_stock_version_positive",
        "loot_table_entry_stock",
        "version >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_loot_table_entry_stock_version_positive",
        "loot_table_entry_stock",
        type_="check",
    )
    op.drop_constraint(
        "ck_loot_table_entries_config_version_positive",
        "loot_table_entries",
        type_="check",
    )
    op.drop_constraint(
        "ck_loot_table_entries_version_positive",
        "loot_table_entries",
        type_="check",
    )
    op.drop_constraint(
        "ck_loot_tables_version_positive",
        "loot_tables",
        type_="check",
    )
    op.drop_constraint(
        "ck_fishing_events_modifier_schema_version_positive",
        "fishing_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_fishing_events_version_positive",
        "fishing_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_fishing_events_status_values",
        "fishing_events",
        type_="check",
    )
    op.alter_column(
        "reward_pools",
        "items_drop_rate",
        existing_type=sa.Numeric(18, 6),
        type_=sa.Float(),
        existing_nullable=False,
        existing_server_default=sa.text("0.1"),
    )
    op.drop_constraint(
        "fk_inventory_item_use_records_inventory_item_id_inventory_items",
        "inventory_item_use_records",
        type_="foreignkey",
    )
    op.alter_column(
        "inventory_item_use_records",
        "inventory_item_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_constraint(
        "uq_loot_table_entry_stock_loot_table_entry_id",
        "loot_table_entry_stock",
        type_="unique",
    )
    op.create_index(
        "ix_loot_table_entry_stock_loot_table_entry_id",
        "loot_table_entry_stock",
        ["loot_table_entry_id"],
        unique=False,
    )
    op.drop_constraint(
        "fk_equipped_items_inventory_item_id_inventory_items",
        "equipped_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_reward_pools_item_loot_table_channel",
        "reward_pools",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "reward_pools_item_loot_table_id_fkey",
        "reward_pools",
        "loot_tables",
        ["item_loot_table_id"],
        ["id"],
        ondelete="SET NULL",
    )
