"""Copy location_items into unified loot tables and link each pool.

Revision ID: 20260802_0015
Revises: 20260802_0014

Safely migrates legacy location drops into the unified loot-table model without
deleting the legacy rows (kept read-only for one release per plan section 8.5).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260802_0015"
down_revision = "20260802_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "location_items" not in inspector.get_table_names():
        return
    if "loot_tables" not in inspector.get_table_names():
        return
    if "reward_pools" not in inspector.get_table_names():
        return

    pool_columns = {column["name"] for column in inspector.get_columns("reward_pools")}
    if "item_loot_table_id" not in pool_columns:
        return

    definitions = set()
    for row in bind.execute(sa.text("SELECT id FROM item_definitions")).fetchall():
        definitions.add(row.id)

    pools = bind.execute(
        sa.text(
            "SELECT p.id, p.location_id, p.location_name, p.item_loot_table_id "
            "FROM reward_pools p"
        )
    ).fetchall()

    for pool in pools:
        pool_id, location_id, location_name, linked = pool
        if linked is not None:
            continue
        has_items = bind.execute(
            sa.text("SELECT COUNT(*) FROM location_items WHERE reward_pool_id = :pid"),
            {"pid": pool_id},
        ).scalar()
        if has_items == 0:
            continue

        table_id = bind.execute(
            sa.text(
                "INSERT INTO loot_tables (channel_id, table_id, title, version, is_active) "
                "SELECT channel_id, :table_id, :title, 1, TRUE FROM reward_pools WHERE id = :pid "
                "RETURNING id"
            ),
            {
                "table_id": f"location:{location_id}",
                "title": location_name or location_id,
                "pid": pool_id,
            },
        ).scalar()

        # location_items.item_id is already the item_definition_id.
        entries = bind.execute(
            sa.text(
                "SELECT li.item_id, li.weight, li.xp_gain, li.quantity, li.message "
                "FROM location_items li WHERE li.reward_pool_id = :pid"
            ),
            {"pid": pool_id},
        ).fetchall()

        for entry in entries:
            definition_id = entry.item_id
            if definition_id not in definitions:
                continue
            loot_entry_id = bind.execute(
                sa.text(
                    "INSERT INTO loot_table_entries "
                    "(loot_table_id, item_definition_id, weight, min_quantity, "
                    "max_quantity, xp_gain, message) "
                    "VALUES (:tid, :def, :weight, 1, 1, :xp, :message) RETURNING id"
                ),
                {
                    "tid": table_id,
                    "def": definition_id,
                    "weight": entry.weight,
                    "xp": entry.xp_gain,
                    "message": entry.message,
                },
            ).scalar()
            if entry.quantity is not None:
                bind.execute(
                    sa.text(
                        "INSERT INTO loot_table_entry_stock "
                        "(loot_table_entry_id, remaining_quantity, version) "
                        "VALUES (:eid, :qty, 1)"
                    ),
                    {"eid": loot_entry_id, "qty": entry.quantity},
                )

        bind.execute(
            sa.text("UPDATE reward_pools SET item_loot_table_id = :tid WHERE id = :pid"),
            {"tid": table_id, "pid": pool_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "reward_pools" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("reward_pools")}
    if "item_loot_table_id" not in columns:
        return
    bind.execute(sa.text("UPDATE reward_pools SET item_loot_table_id = NULL"))
