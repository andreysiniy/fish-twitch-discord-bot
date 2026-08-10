"""Enforce charge bounds across item definitions and inventory rows.

CHECK constraints cannot reference another table.  The service layer already
validates charge values, but PostgreSQL must also protect direct imports and
administrative SQL from creating an inventory row whose charges exceed its
definition (or whose definition is later reduced below existing charges).
"""

from alembic import op


revision = "20260811_0031"
down_revision = "20260811_0030"
branch_labels = None
depends_on = None


_INVENTORY_TRIGGER_FUNCTION = "enforce_inventory_item_charge_bounds"
_DEFINITION_TRIGGER_FUNCTION = "enforce_item_definition_charge_bounds"


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM inventory_items AS inventory
                LEFT JOIN item_definitions AS definition
                  ON definition.id = inventory.item_id
                 AND definition.channel_id = inventory.channel_id
                WHERE inventory.current_charges IS NOT NULL
                  AND (
                      definition.max_charges IS NULL
                      OR inventory.current_charges > definition.max_charges
                  )
            ) THEN
                RAISE EXCEPTION
                    'Cannot enforce charge bounds: existing inventory rows are invalid';
            END IF;
        END $$;
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {_INVENTORY_TRIGGER_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            definition_max_charges integer;
        BEGIN
            IF NEW.current_charges IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT max_charges
              INTO definition_max_charges
              FROM item_definitions
             WHERE id = NEW.item_id
               AND channel_id = NEW.channel_id;

            IF definition_max_charges IS NULL THEN
                RAISE EXCEPTION
                    'current_charges requires a charge-based consumable definition'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.current_charges > definition_max_charges THEN
                RAISE EXCEPTION
                    'current_charges (%) exceeds max_charges (%)',
                    NEW.current_charges,
                    definition_max_charges
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_inventory_items_charge_bounds
        BEFORE INSERT OR UPDATE OF item_id, channel_id, current_charges
        ON inventory_items
        FOR EACH ROW
        EXECUTE FUNCTION {_INVENTORY_TRIGGER_FUNCTION}();
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {_DEFINITION_TRIGGER_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM inventory_items AS inventory
                WHERE inventory.item_id = NEW.id
                  AND inventory.channel_id = NEW.channel_id
                  AND (
                      NEW.max_charges IS NULL
                      OR inventory.current_charges > NEW.max_charges
                  )
                  AND inventory.current_charges IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'max_charges cannot be lower than existing inventory charges'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_item_definitions_charge_bounds
        BEFORE UPDATE OF id, channel_id, max_charges
        ON item_definitions
        FOR EACH ROW
        EXECUTE FUNCTION {_DEFINITION_TRIGGER_FUNCTION}();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_item_definitions_charge_bounds ON item_definitions")
    op.execute("DROP TRIGGER IF EXISTS trg_inventory_items_charge_bounds ON inventory_items")
    op.execute(f"DROP FUNCTION IF EXISTS {_DEFINITION_TRIGGER_FUNCTION}()")
    op.execute(f"DROP FUNCTION IF EXISTS {_INVENTORY_TRIGGER_FUNCTION}()")
