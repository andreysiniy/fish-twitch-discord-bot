"""Add CHECK constraints for economic and version ranges.

Revision ID: 20260802_0010
Revises: 20260802_0009
"""

from alembic import op
from sqlalchemy import inspect

revision = "20260802_0010"
down_revision = "20260802_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # Normalize any pre-existing invalid values deterministically before the
    # constraints are added; this is a safe monotonic clamp, never a deletion.
    op.execute("UPDATE users_progress SET level = GREATEST(level, 1)")
    op.execute("UPDATE users_progress SET xp = GREATEST(xp, 0)")
    op.execute("UPDATE users_progress SET total_fish_stat = GREATEST(total_fish_stat, 0)")
    op.execute("UPDATE users_progress SET current_mass = GREATEST(current_mass, 0)")
    op.execute(
        "UPDATE location_items SET quantity = GREATEST(quantity, 0) "
        "WHERE quantity IS NOT NULL"
    )
    op.execute("UPDATE location_items SET weight = GREATEST(weight, 1)")
    op.execute("UPDATE location_items SET xp_gain = GREATEST(xp_gain, 0)")

    constraints = (
        ("users_progress", "ck_users_progress_level_positive", "level >= 1"),
        ("users_progress", "ck_users_progress_xp_nonnegative", "xp >= 0"),
        (
            "users_progress",
            "ck_users_progress_total_fish_nonnegative",
            "total_fish_stat >= 0",
        ),
        (
            "users_progress",
            "ck_users_progress_current_mass_nonnegative",
            "current_mass >= 0",
        ),
        (
            "reward_pools",
            "ck_reward_pools_items_drop_rate_range",
            "items_drop_rate BETWEEN 0 AND 1",
        ),
        (
            "item_definitions",
            "ck_item_definitions_version_positive",
            "version >= 1",
        ),
        (
            "item_definitions",
            "ck_item_definitions_schema_version_positive",
            "schema_version >= 1",
        ),
        ("location_items", "ck_location_items_weight_positive", "weight > 0"),
        (
            "location_items",
            "ck_location_items_stock_nonnegative",
            "quantity IS NULL OR quantity >= 0",
        ),
        ("location_items", "ck_location_items_xp_nonnegative", "xp_gain >= 0"),
        (
            "player_modifiers",
            "ck_player_modifiers_version_positive",
            "version >= 1",
        ),
        (
            "player_modifiers",
            "ck_player_modifiers_operation",
            "operation IN ('add','multiply','override','min','max')",
        ),
        (
            "player_modifiers",
            "ck_player_modifiers_scope",
            "scope IN ('fishing','robbery','economy','inventory','all')",
        ),
    )

    for table, name, condition in constraints:
        existing = {
            item["name"]
            for item in inspector.get_check_constraints(table)
        }
        if name not in existing:
            op.create_check_constraint(name, table, condition)

    # Preserve the unique/referential shape of fishing events end index.
    events_indexes = {item["name"] for item in inspector.get_indexes("fishing_events")}
    if "ix_fishing_events_ends_at" not in events_indexes:
        op.create_index("ix_fishing_events_ends_at", "fishing_events", ["ends_at"])


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    names = (
        "ck_player_modifiers_scope",
        "ck_player_modifiers_operation",
        "ck_player_modifiers_version_positive",
        "ck_location_items_xp_nonnegative",
        "ck_location_items_stock_nonnegative",
        "ck_location_items_weight_positive",
        "ck_item_definitions_schema_version_positive",
        "ck_item_definitions_version_positive",
        "ck_reward_pools_items_drop_rate_range",
        "ck_users_progress_current_mass_nonnegative",
        "ck_users_progress_total_fish_nonnegative",
        "ck_users_progress_xp_nonnegative",
        "ck_users_progress_level_positive",
    )
    for table in ("users_progress", "reward_pools", "item_definitions", "location_items", "player_modifiers"):
        for name in names:
            existing = {
                item["name"]
                for item in inspector.get_check_constraints(table)
            }
            if name in existing:
                op.drop_constraint(name, table, type_="check")
