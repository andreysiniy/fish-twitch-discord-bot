"""Finalize item value and inventory version semantics.

``ItemDefinition.value`` is an appraisal value, not a wallet balance, so the
public and persistence name is now ``nominal_value``.  Inventory rows already
carry the immutable version obtained at grant time; the old duplicate
``definition_version`` column is removed after a consistency preflight.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260811_0033"
down_revision = "20260811_0032"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inventory_columns = _columns("inventory_items")
    if {"definition_version", "obtained_definition_version"}.issubset(inventory_columns):
        mismatch = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM inventory_items "
                "WHERE definition_version <> obtained_definition_version"
            )
        ).scalar_one()
        if mismatch:
            raise RuntimeError(
                "Cannot remove inventory_items.definition_version: "
                f"{mismatch} rows disagree with obtained_definition_version"
            )
    bind.execute(
        sa.text(
            "ALTER TABLE inventory_items "
            "DROP CONSTRAINT IF EXISTS ck_inventory_items_definition_version_positive"
        )
    )
    if "definition_version" in inventory_columns:
        op.drop_column("inventory_items", "definition_version")

    definition_columns = _columns("item_definitions")
    if {"value", "nominal_value"}.issubset(definition_columns):
        mismatch = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM item_definitions "
                "WHERE value IS NOT NULL AND nominal_value IS NOT NULL "
                "AND value <> nominal_value"
            )
        ).scalar_one()
        if mismatch:
            raise RuntimeError(
                "Cannot finalize item value semantics: value and nominal_value "
                f"disagree in {mismatch} rows"
            )
        bind.execute(
            sa.text(
                "UPDATE item_definitions SET nominal_value = value "
                "WHERE nominal_value IS NULL"
            )
        )
        bind.execute(
            sa.text(
                "ALTER TABLE item_definitions "
                "DROP CONSTRAINT IF EXISTS ck_item_definitions_value_nonnegative"
            )
        )
        op.drop_column("item_definitions", "value")
    elif "value" in definition_columns and "nominal_value" not in definition_columns:
        bind.execute(
            sa.text(
                "ALTER TABLE item_definitions "
                "DROP CONSTRAINT IF EXISTS ck_item_definitions_value_nonnegative"
            )
        )
        op.alter_column("item_definitions", "value", new_column_name="nominal_value")
    elif "nominal_value" not in definition_columns:
        op.add_column("item_definitions", sa.Column("nominal_value", sa.Numeric(18, 2)))
    bind.execute(
        sa.text(
            "ALTER TABLE item_definitions "
            "DROP CONSTRAINT IF EXISTS ck_item_definitions_value_nonnegative"
        )
    )
    bind.execute(
        sa.text(
            "DO $$ BEGIN "
            "ALTER TABLE item_definitions ADD CONSTRAINT "
            "ck_item_definitions_nominal_value_nonnegative "
            "CHECK (nominal_value IS NULL OR nominal_value >= 0); "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "ALTER TABLE item_definitions "
            "DROP CONSTRAINT IF EXISTS ck_item_definitions_nominal_value_nonnegative"
        )
    )
    definition_columns = _columns("item_definitions")
    if "nominal_value" in definition_columns and "value" not in definition_columns:
        op.alter_column("item_definitions", "nominal_value", new_column_name="value")
    bind.execute(
        sa.text(
            "DO $$ BEGIN "
            "ALTER TABLE item_definitions ADD CONSTRAINT ck_item_definitions_value_nonnegative "
            "CHECK (value IS NULL OR value >= 0); "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
        )
    )

    inventory_columns = _columns("inventory_items")
    if "definition_version" not in inventory_columns:
        op.add_column(
            "inventory_items",
            sa.Column("definition_version", sa.Integer(), nullable=False, server_default="1"),
        )
        bind.execute(
            sa.text(
                "UPDATE inventory_items SET definition_version = obtained_definition_version"
            )
        )
        op.alter_column("inventory_items", "definition_version", server_default=None)
    bind.execute(
        sa.text(
            "DO $$ BEGIN "
            "ALTER TABLE inventory_items ADD CONSTRAINT "
            "ck_inventory_items_definition_version_positive CHECK (definition_version >= 1); "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
        )
    )
