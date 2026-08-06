"""Finalize the unified loot-table migration and PostgreSQL event deadlines.

1. Adds a partial index on active fishing events (ends_at) so the PostgreSQL
   event worker can find due events without scanning.
2. Backfills a unified loot table for every reward pool that still only has
   legacy location_items rows (data-preserving copy), then links the pool.
3. Drops the legacy ``location_items`` table. Admin item-drop mutations now
   operate exclusively on loot_tables / loot_table_entries / stock.

Revision ID: 20260802_0022
Revises: 20260802_0021
"""

from alembic import op
from sqlalchemy import inspect, text

revision = "20260802_0022"
down_revision = "20260802_0021"
branch_labels = None
depends_on = None


def _create_index_if_missing(bind, table: str, name: str, ddl: str) -> None:
    existing = {i["name"] for i in inspect(bind).get_indexes(table)}
    if name not in existing:
        op.execute(ddl)


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. partial index for the PostgreSQL event worker -----------------
    _create_index_if_missing(
        bind,
        "fishing_events",
        "ix_fishing_events_active_ends_at",
        "CREATE INDEX ix_fishing_events_active_ends_at ON fishing_events (ends_at) "
        "WHERE is_active = true",
    )

    # --- 2. backfill unified loot tables for legacy-only pools -------------
    tables_present = {
        row[0]
        for row in bind.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).fetchall()
    }
    if "location_items" in tables_present:
        pools = bind.execute(
            text(
                "SELECT p.id, p.channel_id, p.location_id FROM reward_pools p "
                "WHERE p.item_loot_table_id IS NULL "
                "AND EXISTS (SELECT 1 FROM location_items li WHERE li.reward_pool_id = p.id)"
            )
        ).fetchall()
    for pool_id, channel_id, location_id in pools:
        pool_row = bind.execute(
            text(
                "SELECT location_name FROM reward_pools WHERE id = :pid"
            ),
            {"pid": pool_id},
        ).scalar()
        table_id = f"legacy-{location_id}"
        loot_table_id = bind.execute(
            text(
                "INSERT INTO loot_tables (channel_id, table_id, title, version, is_active, "
                "created_at, updated_at) VALUES (:channel, :table_id, :title, 1, true, "
                "now(), now()) RETURNING id"
            ),
            {"channel": channel_id, "table_id": table_id, "title": pool_row or location_id},
        ).scalar()
        legacy_rows = bind.execute(
            text(
                "SELECT item_id, weight, xp_gain, quantity, message FROM location_items "
                "WHERE reward_pool_id = :pool ORDER BY id"
            ),
            {"pool": pool_id},
        ).fetchall()
        for item_id, weight, xp_gain, quantity, message in legacy_rows:
            entry_id = bind.execute(
                text(
                    "INSERT INTO loot_table_entries (channel_id, loot_table_id, "
                    "item_definition_id, weight, min_quantity, max_quantity, "
                    "xp_gain, message, config_version) "
                    "VALUES (:channel, :table, :item, :weight, 1, 1, :xp, :message, 1) "
                    "RETURNING id"
                ),
                {
                    "channel": channel_id,
                    "table": loot_table_id,
                    "item": item_id,
                    "weight": weight,
                    "xp": xp_gain or 0,
                    "message": message,
                },
            ).scalar()
            if quantity is not None and int(quantity) > 0:
                bind.execute(
                    text(
                        "INSERT INTO loot_table_entry_stock (loot_table_entry_id, "
                        "remaining_quantity, version, updated_at) "
                        "VALUES (:entry, :quantity, 1, now())"
                    ),
                    {"entry": entry_id, "quantity": int(quantity)},
                )
        bind.execute(
            text("UPDATE reward_pools SET item_loot_table_id = :table WHERE id = :pool"),
            {"table": loot_table_id, "pool": pool_id},
        )

    # --- 3. drop the legacy location_items table ---------------------------
    existing = {t for (t,) in bind.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    ).fetchall()}
    if "location_items" in existing:
        op.drop_table("location_items")


def downgrade() -> None:
    """Recreate location_items from loot-table entries (best-effort reverse)."""
    op.create_table(
        "location_items",
        op.Column("id", op.Integer(), primary_key=True),
        op.Column("reward_pool_id", op.Integer(), nullable=False),
        op.Column("item_id", op.Integer(), nullable=False),
        op.Column("weight", op.Integer(), nullable=False),
        op.Column("xp_gain", op.Integer(), nullable=False),
        op.Column("quantity", op.Integer(), nullable=True),
        op.Column("message", op.String(), nullable=True),
        op.Column("version", op.Integer(), nullable=False),
    )
