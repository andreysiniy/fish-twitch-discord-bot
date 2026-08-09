"""Split consume_charge semantics and add charge-based consumables.

Spec 11.4 fixes the semantic mismatch where the ``consume_charge`` effect
actually consumed equipment durability. Two distinct runtime effects now exist:

- ``consume_durability`` -> equipment only -> changes current_durability
- ``consume_charge``     -> consumable only -> changes current_charges

Schema changes:

- item_definitions.max_charges (nullable int, consumable-only, positive,
  requires stack_size 1 because each charge-based instance is its own row).
- inventory_items.current_charges (nullable int, non-negative).
- item_definitions.max_durability is now equipment-only (already
  indestructible-by-default; a preflight report guards against legacy rows).

Data migration: legacy ``consume_charge`` effects were always durability
consumption at runtime, so they are renamed to ``consume_durability``. This is
a non-destructive type rename, preserving the exact old behavior (spec 11.4).

Revision ID: 20260806_0027
Revises: 20260806_0026
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "20260806_0027"
down_revision = "20260806_0026"
branch_labels = None
depends_on = None


def _as_list(effects) -> list:
    if effects is None:
        return []
    if isinstance(effects, str):
        return json.loads(effects)
    if isinstance(effects, list):
        return effects
    return [effects]


def _rewrite_effects(effects) -> list:
    """Rename legacy consume_charge effects to consume_durability.

    Preserves every other field verbatim; the rename only changes the effect
    discriminator, so no game data is discarded.
    """
    migrated = []
    for effect in effects or []:
        if isinstance(effect, dict) and effect.get("type") == "consume_charge":
            migrated.append({**effect, "type": "consume_durability"})
        else:
            migrated.append(effect)
    return migrated


def upgrade() -> None:
    bind = op.get_bind()

    # Preflight: non-equipment rows must not carry durability once the new
    # equipment-only CHECK constraint is added (spec 11.4).
    non_equipment_durability = bind.execute(
        text(
            "SELECT item_id FROM item_definitions "
            "WHERE type <> 'equipment' AND max_durability IS NOT NULL"
        )
    ).fetchall()
    if non_equipment_durability:
        raise RuntimeError(
            "Cannot enforce durability-equipment-only: non-equipment items "
            "still carry max_durability: " + ", ".join(row[0] for row in non_equipment_durability)
        )

    op.add_column(
        "item_definitions",
        sa.Column("max_charges", sa.Integer(), nullable=True),
    )
    op.add_column(
        "inventory_items",
        sa.Column("current_charges", sa.Integer(), nullable=True),
    )

    op.create_check_constraint(
        "ck_item_definitions_charges_consumable_only",
        "item_definitions",
        "type = 'consumable' OR max_charges IS NULL",
    )
    op.create_check_constraint(
        "ck_item_definitions_max_charges_positive",
        "item_definitions",
        "max_charges IS NULL OR max_charges > 0",
    )
    op.create_check_constraint(
        "ck_item_definitions_charges_single_stack",
        "item_definitions",
        "max_charges IS NULL OR stack_size = 1",
    )
    op.create_check_constraint(
        "ck_item_definitions_durability_equipment_only",
        "item_definitions",
        "type = 'equipment' OR max_durability IS NULL",
    )
    op.create_check_constraint(
        "ck_inventory_items_charges_nonnegative",
        "inventory_items",
        "current_charges IS NULL OR current_charges >= 0",
    )

    # Rewrite legacy consume_charge -> consume_durability.
    effect_rows = bind.execute(
        text("SELECT id, effects FROM item_definitions WHERE jsonb_typeof(effects) = 'array'")
    ).fetchall()
    for item_id, effects in effect_rows:
        migrated = _rewrite_effects(_as_list(effects))
        bind.execute(
            text("UPDATE item_definitions SET effects = :effects WHERE id = :id"),
            {"effects": json.dumps(migrated), "id": item_id},
        )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_constraint(
        "ck_inventory_items_charges_nonnegative",
        "inventory_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_item_definitions_durability_equipment_only",
        "item_definitions",
        type_="check",
    )
    op.drop_constraint(
        "ck_item_definitions_charges_single_stack",
        "item_definitions",
        type_="check",
    )
    op.drop_constraint(
        "ck_item_definitions_max_charges_positive",
        "item_definitions",
        type_="check",
    )
    op.drop_constraint(
        "ck_item_definitions_charges_consumable_only",
        "item_definitions",
        type_="check",
    )
    op.drop_column("inventory_items", "current_charges")
    op.drop_column("item_definitions", "max_charges")

    # Reverse the rename for stored effects.
    for item_id, effects in bind.execute(
        text("SELECT id, effects FROM item_definitions WHERE jsonb_typeof(effects) = 'array'")
    ).fetchall():
        reverted = []
        for effect in _as_list(effects):
            if isinstance(effect, dict) and effect.get("type") == "consume_durability":
                reverted.append({**effect, "type": "consume_charge"})
            else:
                reverted.append(effect)
        bind.execute(
            text("UPDATE item_definitions SET effects = :effects WHERE id = :id"),
            {"effects": json.dumps(reverted), "id": item_id},
        )
