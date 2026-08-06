"""Make location item drops independently versioned and unique."""

from alembic import op
from sqlalchemy import inspect


revision = "20260802_0004"
down_revision = "20260802_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    constraints = {
        item["name"] for item in inspector.get_unique_constraints("location_items")
    }
    if "uq_location_items_pool_item" in constraints:
        return
    # Preflight: duplicates with differing content must not be deleted
    # silently. Identical duplicates are collapsed deterministically (keep
    # the lowest id) without any data loss.
    differing = bind.exec_driver_sql(
        """
        SELECT d.reward_pool_id, d.item_id, count(*) AS groups
        FROM location_items d
        GROUP BY d.reward_pool_id, d.item_id
        HAVING count(*) > 1
          AND (
            count(DISTINCT weight) > 1
            OR count(DISTINCT xp_gain) > 1
            OR count(DISTINCT COALESCE(quantity, -1)) > 1
            OR count(DISTINCT message) > 1
          )
        """
    ).fetchall()
    if differing:
        raise RuntimeError(
            "Cannot deduplicate location_items: rows with identical "
            f"(reward_pool_id, item_id) have different weight/xp/quantity/message "
            f"({len(differing)} group(s)); merge them manually first"
        )
    bind.exec_driver_sql(
        """
        DELETE FROM location_items AS duplicate
        USING location_items AS retained
        WHERE duplicate.reward_pool_id = retained.reward_pool_id
          AND duplicate.item_id = retained.item_id
          AND duplicate.id > retained.id
        """
    )
    op.create_unique_constraint(
        "uq_location_items_pool_item",
        "location_items",
        ["reward_pool_id", "item_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_location_items_pool_item", "location_items", type_="unique"
    )
