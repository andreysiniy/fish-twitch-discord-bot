"""Enforce same-owner equipment ownership and tenant-aware inventory keys.

Revision ID: 20260802_0008
Revises: 20260802_0007
"""

from alembic import op
from sqlalchemy import inspect

revision = "20260802_0008"
down_revision = "20260802_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())

    # 1. Composite unique key (id, user_id) that the equipment FK will target.
    uniques = {
        item["name"]
        for item in inspector.get_unique_constraints("inventory_items")
    }
    if "uq_inventory_item_id_user" not in uniques:
        op.create_unique_constraint(
            "uq_inventory_item_id_user", "inventory_items", ["id", "user_id"]
        )

    # 2. Drop the old single-column FK on equipped_items.inventory_item_id.
    fks = inspector.get_foreign_keys("equipped_items")
    legacy = [fk for fk in fks if set(fk.get("constrained_columns", [])) == {"inventory_item_id"}]
    for fk in legacy:
        op.drop_constraint(fk["name"], "equipped_items", type_="foreignkey")

    # 3. Add the composite ownership FK.
    if "fk_equipped_items_inventory_owner" not in {
        fk["name"] for fk in inspector.get_foreign_keys("equipped_items")
    }:
        op.create_foreign_key(
            "fk_equipped_items_inventory_owner",
            "equipped_items",
            "inventory_items",
            ["inventory_item_id", "user_id"],
            ["id", "user_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if "fk_equipped_items_inventory_owner" in {
        fk["name"] for fk in inspector.get_foreign_keys("equipped_items")
    }:
        op.drop_constraint(
            "fk_equipped_items_inventory_owner", "equipped_items", type_="foreignkey"
        )
        op.create_foreign_key(
            "fk_equipped_items_inventory_item_id",
            "equipped_items",
            "inventory_items",
            ["inventory_item_id"],
            ["id"],
            ondelete="CASCADE",
        )
    if "uq_inventory_item_id_user" in {
        item["name"]
        for item in inspector.get_unique_constraints("inventory_items")
    }:
        op.drop_constraint(
            "uq_inventory_item_id_user", "inventory_items", type_="unique"
        )
