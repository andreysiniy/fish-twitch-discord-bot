"""Enforce tenant ownership and missing constraints with composite FKs.

Adds ``UNIQUE (id, channel_id)`` to parent tables and composite foreign keys so
PostgreSQL itself rejects cross-channel references:

- inventory_items(user_id, channel_id)      -> users_progress(id, channel_id)
- inventory_items(item_definition_id, channel_id) -> item_definitions(id, channel_id)
- location_items(reward_pool_id, channel_id) -> reward_pools(id, channel_id)
- location_items(item_id, channel_id)       -> item_definitions(id, channel_id)
- loot_table_entries(loot_table_id, channel_id) -> loot_tables(id, channel_id)
- loot_table_entries(item_definition_id, channel_id) -> item_definitions(id, channel_id)
- player_modifiers(user_progress_id, channel_id) -> users_progress(id, channel_id)
- economy_operations(user_id, channel_id)   -> users_progress(id, channel_id)
- fishing_casts(user_progress_id, channel_id) -> users_progress(id, channel_id)
- fishing_cast_item_drops(cast_id, channel_id) -> fishing_casts(id, channel_id)

Also adds the missing CHECK constraints from database_models_audit.md section 4,
the loot-table uniqueness/stock checks, and drops redundant indexes that
duplicate unique constraints.

Revision ID: 20260802_0020
Revises: 20260802_0019
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text

revision = "20260802_0020"
down_revision = "20260802_0019"
branch_labels = None
depends_on = None

_PARENT_UNIQUES = [
    ("users_progress", "uq_users_progress_id_channel", ["id", "channel_id"]),
    ("item_definitions", "uq_item_definitions_id_channel", ["id", "channel_id"]),
    ("reward_pools", "uq_reward_pools_id_channel", ["id", "channel_id"]),
    ("loot_tables", "uq_loot_tables_id_channel", ["id", "channel_id"]),
    ("fishing_casts", "uq_fishing_casts_id_channel", ["id", "channel_id"]),
]

# child table, new column, backfill join, composite FK name, columns, parent, parent cols, ondelete
_COMPOSITE_FKS = [
    (
        "inventory_items",
        "channel_id",
        "UPDATE inventory_items child SET channel_id = parent.channel_id "
        "FROM users_progress parent WHERE child.user_id = parent.id",
        "fk_inventory_items_user_channel",
        ["user_id", "channel_id"],
        "users_progress",
        ["id", "channel_id"],
        "CASCADE",
    ),
    (
        "inventory_items",
        "channel_id",
        None,
        "fk_inventory_items_item_channel",
        ["item_id", "channel_id"],
        "item_definitions",
        ["id", "channel_id"],
        None,
    ),
    (
        "location_items",
        "channel_id",
        "UPDATE location_items child SET channel_id = parent.channel_id "
        "FROM reward_pools parent WHERE child.reward_pool_id = parent.id",
        "fk_location_items_pool_channel",
        ["reward_pool_id", "channel_id"],
        "reward_pools",
        ["id", "channel_id"],
        None,
    ),
    (
        "location_items",
        "channel_id",
        None,
        "fk_location_items_item_channel",
        ["item_id", "channel_id"],
        "item_definitions",
        ["id", "channel_id"],
        None,
    ),
    (
        "loot_table_entries",
        "channel_id",
        "UPDATE loot_table_entries child SET channel_id = parent.channel_id "
        "FROM loot_tables parent WHERE child.loot_table_id = parent.id",
        "fk_loot_table_entries_table_channel",
        ["loot_table_id", "channel_id"],
        "loot_tables",
        ["id", "channel_id"],
        "CASCADE",
    ),
    (
        "loot_table_entries",
        "channel_id",
        None,
        "fk_loot_table_entries_item_channel",
        ["item_definition_id", "channel_id"],
        "item_definitions",
        ["id", "channel_id"],
        None,
    ),
    (
        "player_modifiers",
        None,
        None,
        "fk_player_modifiers_user_channel",
        ["user_progress_id", "channel_id"],
        "users_progress",
        ["id", "channel_id"],
        "CASCADE",
    ),
    (
        "economy_operations",
        None,
        None,
        "fk_economy_operations_user_channel",
        ["user_id", "channel_id"],
        "users_progress",
        ["id", "channel_id"],
        None,
    ),
    (
        "fishing_casts",
        None,
        None,
        "fk_fishing_casts_user_channel",
        ["user_progress_id", "channel_id"],
        "users_progress",
        ["id", "channel_id"],
        None,
    ),
    (
        "fishing_cast_item_drops",
        None,
        None,
        "fk_fishing_cast_item_drops_cast_channel",
        ["cast_id", "channel_id"],
        "fishing_casts",
        ["id", "channel_id"],
        "CASCADE",
    ),
    (
        "fishing_cast_item_drops",
        None,
        None,
        "fk_fishing_cast_item_drops_item_channel",
        ["item_definition_id", "channel_id"],
        "item_definitions",
        ["id", "channel_id"],
        None,
    ),
]


def _fk_by_referenced(bind, table: str, referenced: str) -> list[str]:
    inspector = inspect(bind)
    names = []
    for fk in inspector.get_foreign_keys(table):
        if fk.get("referred_table") == referenced:
            names.append(fk["name"])
    return names


def _drop_foreign_keys(bind, table: str, referenced: str) -> None:
    for name in _fk_by_referenced(bind, table, referenced):
        op.drop_constraint(name, table, type_="foreignkey")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # --- 1. parent unique keys (id, channel_id) -------------------------
    for table, name, columns in _PARENT_UNIQUES:
        existing = {u["name"] for u in inspector.get_unique_constraints(table)}
        if name not in existing:
            op.create_unique_constraint(name, table, columns)

    # --- 2. backfill + add channel_id columns ---------------------------
    for child, column, backfill, fk_name, columns, parent, parent_cols, ondelete in _COMPOSITE_FKS:
        if column is None:
            continue
        fresh = inspect(bind)
        cols = {c["name"] for c in fresh.get_columns(child)}
        if column not in cols:
            op.add_column(child, sa.Column(column, sa.Integer(), nullable=True))
        if backfill:
            op.execute(text(backfill))
        # Orphan rows (no parent) must abort the migration instead of
        # producing a silently broken tenant graph.
        orphans = bind.execute(
            text(
                f"SELECT count(*) FROM {child} c "
                f"WHERE NOT EXISTS (SELECT 1 FROM {parent} p WHERE p.id = c.{columns[0]})"
            )
        ).scalar()
        if orphans:
            raise RuntimeError(
                f"Cannot enforce tenant FKs on {child}: {orphans} orphan row(s) "
                "without a parent"
            )
        # Set NOT NULL after backfill.
        op.alter_column(child, column, nullable=False)

    # --- 3. replace single-column FKs with composite FKs -----------------
    replacements = [
        ("inventory_items", "users_progress"),
        ("inventory_items", "item_definitions"),
        ("location_items", "reward_pools"),
        ("location_items", "item_definitions"),
        ("loot_table_entries", "loot_tables"),
        ("loot_table_entries", "item_definitions"),
        ("player_modifiers", "users_progress"),
        ("economy_operations", "users_progress"),
        ("fishing_casts", "users_progress"),
        ("fishing_cast_item_drops", "fishing_casts"),
        ("fishing_cast_item_drops", "item_definitions"),
    ]
    for child, referenced in replacements:
        _drop_foreign_keys(bind, child, referenced)

    for child, column, backfill, fk_name, columns, parent, parent_cols, ondelete in (
        _COMPOSITE_FKS
    ):
        op.create_foreign_key(
            fk_name,
            child,
            parent,
            columns,
            parent_cols,
            ondelete=ondelete,
        )

    # --- 4. missing CHECK constraints -----------------------------------
    def _create_check(table: str, name: str, condition: str) -> None:
        current_inspector = inspect(op.get_bind())
        existing = {
            c["name"] for c in current_inspector.get_check_constraints(table)
        }
        if name not in existing:
            op.create_check_constraint(name, table, condition)

    _create_check(
        "item_definitions",
        "ck_item_definitions_value_nonnegative",
        "value IS NULL OR value >= 0",
    )
    _create_check(
        "inventory_items",
        "ck_inventory_items_version_positive",
        "version >= 1",
    )
    _create_check(
        "inventory_items",
        "ck_inventory_items_definition_version_positive",
        "definition_version >= 1",
    )
    _create_check(
        "reward_pools",
        "ck_reward_pools_version_positive",
        "version >= 1",
    )
    _create_check(
        "location_items",
        "ck_location_items_version_positive",
        "version >= 1",
    )
    _create_check(
        "users_progress",
        "ck_users_progress_base_inventory_slots_positive",
        "base_inventory_slots >= 1",
    )
    _create_check(
        "loot_table_entries",
        "ck_loot_table_entries_xp_nonnegative",
        "xp_gain >= 0",
    )
    _create_check(
        "loot_table_entry_stock",
        "ck_loot_table_entry_stock_remaining_nonnegative",
        "remaining_quantity >= 0",
    )

    # --- 5. loot table entry uniqueness and config version ---------------
    existing = {u["name"] for u in inspector.get_unique_constraints("loot_table_entries")}
    if "uq_loot_table_entries_table_item" not in existing:
        duplicates = bind.execute(
            text(
                "SELECT loot_table_id, item_definition_id, count(*) FROM loot_table_entries "
                "GROUP BY loot_table_id, item_definition_id HAVING count(*) > 1"
            )
        ).fetchall()
        if duplicates:
            raise RuntimeError(
                "Cannot add unique (loot_table_id, item_definition_id): duplicate entries "
                f"exist ({len(duplicates)} group(s)); merge them manually first"
            )
        op.create_unique_constraint(
            "uq_loot_table_entries_table_item",
            "loot_table_entries",
            ["loot_table_id", "item_definition_id"],
        )

    entry_columns = {c["name"] for c in inspector.get_columns("loot_table_entries")}
    if "config_version" not in entry_columns:
        op.add_column(
            "loot_table_entries",
            sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        )

    # --- 6. redundant indexes that duplicate unique constraints ----------
    redundant = [
        ("channels", "ix_channels_twitch_id"),
        ("discord_account_links", "ix_discord_account_links_discord_user_id"),
        ("discord_account_links", "ix_discord_account_links_twitch_user_id"),
        ("discord_guild_bindings", "ix_discord_guild_bindings_discord_guild_id"),
        ("discord_guild_bindings", "ix_discord_guild_bindings_channel_id"),
    ]
    for table, index_name in redundant:
        existing = {i["name"] for i in inspector.get_indexes(table)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table)

    # --- 7. index the new inventory tenant column ------------------------
    inventory_indexes = {i["name"] for i in inspect(bind).get_indexes("inventory_items")}
    if "ix_inventory_items_channel_id" not in inventory_indexes:
        op.create_index(
            "ix_inventory_items_channel_id", "inventory_items", ["channel_id"]
        )


def downgrade() -> None:
    """Best-effort reverse: drop composite FKs, checks, uniques and columns."""
    for child, column, backfill, fk_name, columns, parent, parent_cols, ondelete in reversed(
        _COMPOSITE_FKS
    ):
        op.drop_constraint(fk_name, child, type_="foreignkey")
    for table, name, columns in reversed(_PARENT_UNIQUES):
        op.drop_constraint(name, table, type_="unique")
    for child, column, backfill, *_ in _COMPOSITE_FKS:
        if column is not None:
            op.drop_column(child, column)
    for name in (
        "ck_item_definitions_value_nonnegative",
        "ck_inventory_items_version_positive",
        "ck_inventory_items_definition_version_positive",
        "ck_reward_pools_version_positive",
        "ck_location_items_version_positive",
        "ck_users_progress_base_inventory_slots_positive",
        "ck_loot_table_entries_xp_nonnegative",
        "ck_loot_table_entry_stock_remaining_nonnegative",
    ):
        try:
            op.drop_constraint(name, None, type_="check")
        except Exception:  # pragma: no cover - defensive
            pass
    op.drop_constraint("uq_loot_table_entries_table_item", "loot_table_entries", type_="unique")
    op.drop_column("loot_table_entries", "config_version")
