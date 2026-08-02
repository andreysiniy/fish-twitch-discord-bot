"""Add the typed item, equipment, loot table, and player modifier schema."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "20260802_0003"
down_revision = "20260802_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    _add_column(inspector, "item_definitions", sa.Column("max_durability", sa.Integer()))
    _add_column(
        inspector,
        "item_definitions",
        sa.Column("break_policy", sa.String(), nullable=False, server_default="indestructible"),
    )
    _add_column(
        inspector,
        "item_definitions",
        sa.Column(
            "effects",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    _add_column(inspector, "item_definitions", sa.Column("value", sa.Numeric(18, 2)))
    _add_column(inspector, "item_definitions", sa.Column("sell_value", sa.Numeric(18, 2)))
    _add_column(
        inspector,
        "item_definitions",
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column(
        inspector,
        "item_definitions",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column(
        inspector,
        "item_definitions",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    _add_column(inspector, "item_definitions", sa.Column("archived_at", sa.DateTime(timezone=True)))
    _add_column(
        inspector,
        "item_definitions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    _add_column(inspector, "item_definitions", sa.Column("updated_by", sa.String()))
    _add_column(
        inspector,
        "inventory_items",
        sa.Column("definition_version", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column(
        inspector,
        "inventory_items",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column(
        inspector,
        "location_items",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column(
        inspector,
        "location_items",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    _add_column(
        inspector,
        "outbox_events",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    )
    if "ix_outbox_events_lease_expires_at" not in {
        item["name"] for item in inspector.get_indexes("outbox_events")
    }:
        op.create_index(
            "ix_outbox_events_lease_expires_at", "outbox_events", ["lease_expires_at"]
        )
    _add_column(
        inspector,
        "economy_operations",
        sa.Column("compensated_at", sa.DateTime(timezone=True)),
    )

    op.execute(
        "UPDATE item_definitions SET max_durability = durability "
        "WHERE max_durability IS NULL AND durability IS NOT NULL"
    )
    op.execute(
        "UPDATE item_definitions SET stack_size = 1 WHERE type = 'equipment' OR slot IS NOT NULL"
    )
    op.execute(
        "UPDATE item_definitions SET type = 'equipment' "
        "WHERE type IN ('rod','bait','defense','storage') OR "
        "slot IN ('rod','bait','defense','storage','charm_1','charm_2')"
    )
    op.execute(
        "UPDATE item_definitions SET type = 'collectible' "
        "WHERE type NOT IN ('equipment','consumable','lootbox','material','quest','currency','collectible')"
    )
    op.execute(
        "UPDATE item_definitions SET slot = NULL "
        "WHERE slot IS NOT NULL AND slot NOT IN ('rod','bait','defense','storage','charm_1','charm_2')"
    )
    op.execute(
        "UPDATE item_definitions SET rarity = 'common' "
        "WHERE rarity NOT IN ('common','rare','epic','legendary')"
    )
    op.execute("UPDATE inventory_items SET quantity = GREATEST(quantity, 1)")
    op.execute("UPDATE inventory_items SET slot_id = GREATEST(slot_id, 1)")
    op.execute(
        "UPDATE inventory_items SET current_durability = GREATEST(current_durability, 0) "
        "WHERE current_durability IS NOT NULL"
    )

    inspector = inspect(bind)
    _create_equipped_items(inspector)
    _create_player_modifiers(inspector)
    _create_loot_tables(inspector)
    _create_item_use_records(inspector)
    _add_constraints(inspect(bind))
    _migrate_legacy_effects()
    _migrate_equipped_rods()


def downgrade() -> None:
    op.drop_table("inventory_item_use_records")
    op.drop_table("loot_table_entries")
    op.drop_table("loot_tables")
    op.drop_table("player_modifiers")
    op.drop_table("equipped_items")
    op.drop_column("economy_operations", "compensated_at")
    op.drop_index("ix_outbox_events_lease_expires_at", table_name="outbox_events")
    op.drop_column("outbox_events", "lease_expires_at")
    op.drop_column("location_items", "updated_at")
    op.drop_column("location_items", "version")
    op.drop_column("inventory_items", "version")
    op.drop_column("inventory_items", "definition_version")
    for column in (
        "updated_by",
        "updated_at",
        "archived_at",
        "is_active",
        "version",
        "schema_version",
        "sell_value",
        "value",
        "effects",
        "break_policy",
        "max_durability",
    ):
        op.drop_column("item_definitions", column)


def _add_column(inspector, table_name: str, column: sa.Column) -> None:
    if column.name not in {item["name"] for item in inspector.get_columns(table_name)}:
        op.add_column(table_name, column)


def _create_equipped_items(inspector) -> None:
    if "equipped_items" in inspector.get_table_names():
        return
    op.create_table(
        "equipped_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users_progress.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slot", sa.String(), nullable=False),
        sa.Column(
            "inventory_item_id",
            sa.Integer(),
            sa.ForeignKey("inventory_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "slot", name="uq_equipped_items_user_slot"),
        sa.UniqueConstraint("inventory_item_id", name="uq_equipped_items_inventory_item"),
        sa.CheckConstraint(
            "slot IN ('rod','bait','defense','storage','charm_1','charm_2')",
            name="ck_equipped_items_slot",
        ),
    )


def _create_player_modifiers(inspector) -> None:
    if "player_modifiers" in inspector.get_table_names():
        return
    op.create_table(
        "player_modifiers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "user_progress_id",
            sa.Integer(),
            sa.ForeignKey("users_progress.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stat_key", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=False),
        sa.Column("scope", sa.String(), nullable=False, server_default="all"),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_twitch_id", sa.String(), nullable=False),
        sa.Column("created_by_discord_id", sa.String()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "channel_id", "user_progress_id", "stat_key", "scope", "source_key",
            name="uq_player_modifiers_source",
        ),
        sa.CheckConstraint(
            "operation IN ('add','multiply','override','min','max')",
            name="ck_player_modifiers_operation",
        ),
        sa.CheckConstraint(
            "scope IN ('fishing','robbery','economy','inventory','all')",
            name="ck_player_modifiers_scope",
        ),
    )
    op.create_index("ix_player_modifiers_expires_at", "player_modifiers", ["expires_at"])


def _create_loot_tables(inspector) -> None:
    if "loot_tables" not in inspector.get_table_names():
        op.create_table(
            "loot_tables",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("channel_id", sa.Integer(), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
            sa.Column("table_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("channel_id", "table_id", name="uq_loot_tables_channel_table"),
        )
    if "loot_table_entries" not in inspector.get_table_names():
        op.create_table(
            "loot_table_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("loot_table_id", sa.Integer(), sa.ForeignKey("loot_tables.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "item_definition_id", sa.Integer(),
                sa.ForeignKey("item_definitions.id", ondelete="RESTRICT"), nullable=False,
            ),
            sa.Column("weight", sa.Integer(), nullable=False),
            sa.Column("min_quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("max_quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("rarity_filter", sa.String()),
            sa.CheckConstraint("weight > 0", name="ck_loot_table_entries_weight_positive"),
            sa.CheckConstraint("min_quantity > 0", name="ck_loot_table_entries_min_quantity_positive"),
            sa.CheckConstraint("max_quantity >= min_quantity", name="ck_loot_table_entries_quantity_range"),
        )


def _create_item_use_records(inspector) -> None:
    if "inventory_item_use_records" in inspector.get_table_names():
        return
    op.create_table(
        "inventory_item_use_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users_progress.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_item_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column(
            "response_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_item_use_user_key"),
    )


def _add_constraints(inspector) -> None:
    existing = {
        item["name"]
        for table in ("item_definitions", "inventory_items")
        for item in inspector.get_check_constraints(table)
    }
    constraints = (
        ("item_definitions", "ck_item_definitions_stack_size_positive", "stack_size > 0"),
        (
            "item_definitions", "ck_item_definitions_equipment_single_stack",
            "type <> 'equipment' OR stack_size = 1",
        ),
        (
            "item_definitions", "ck_item_definitions_max_durability_positive",
            "max_durability IS NULL OR max_durability > 0",
        ),
        (
            "item_definitions", "ck_item_definitions_type",
            "type IN ('equipment','consumable','lootbox','material','quest','currency','collectible')",
        ),
        (
            "item_definitions", "ck_item_definitions_slot",
            "slot IS NULL OR slot IN ('rod','bait','defense','storage','charm_1','charm_2')",
        ),
        (
            "item_definitions", "ck_item_definitions_rarity",
            "rarity IN ('common','rare','epic','legendary')",
        ),
        (
            "item_definitions", "ck_item_definitions_break_policy",
            "break_policy IN ('indestructible','retain_broken','unequip_broken','destroy_at_zero')",
        ),
        ("inventory_items", "ck_inventory_items_quantity_positive", "quantity > 0"),
        ("inventory_items", "ck_inventory_items_slot_positive", "slot_id >= 1"),
        (
            "inventory_items", "ck_inventory_items_durability_nonnegative",
            "current_durability IS NULL OR current_durability >= 0",
        ),
    )
    for table, name, condition in constraints:
        if name not in existing:
            op.create_check_constraint(name, table, condition)


def _migrate_legacy_effects() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        UPDATE item_definitions
        SET effects = CASE
            WHEN item_id = 'rod_carbon' THEN
                '[{"type":"stat_add","stat":"positive_mass_bonus_pct","value":"0.15"},'
                '{"type":"stat_add","stat":"xp_gain_bonus_pct","value":"0.15"}]'::jsonb
            WHEN item_id = 'rod_bamboo' THEN
                '[{"type":"stat_add","stat":"loot_luck_pct","value":"0.05"}]'::jsonb
            WHEN item_id = 'bait_magnet' THEN
                '[{"type":"stat_add","stat":"item_drop_chance_add","value":"0.10"}]'::jsonb
            WHEN item_id = 'bait_clover' THEN
                '[{"type":"reroll_reward","trigger":"after_reward_roll",'
                '"target_action_types":["nothing"],"max_rerolls":1}]'::jsonb
            WHEN item_id = 'def_electric_eel' THEN
                '[{"type":"robbery_counter","trigger":"on_robbery_attempt","chance":"1",'
                '"action":{"type":"timeout","duration_seconds":30,'
                '"reason":"Zapped by Electric Eel"},"durability_cost":1}]'::jsonb
            WHEN item_id = 'def_decoy_fish' THEN
                '[{"type":"absorb_robbery","trigger":"on_robbery_attempt","chance":"1",'
                '"attacker_mass_delta":"-5","durability_cost":1}]'::jsonb
            WHEN item_id = 'storage_titanium_net' THEN
                '[{"type":"stat_add","stat":"negative_mass_reduction_pct","value":"0.50"}]'::jsonb
            WHEN item_id = 'storage_smugglers_safe' THEN
                '[{"type":"mass_floor","protected_mass":"1000",'
                '"scopes":["robbery","negative_rewards","roulette"]}]'::jsonb
            ELSE COALESCE(effects, '[]'::jsonb)
        END,
        max_durability = COALESCE(
            max_durability,
            CASE
                WHEN (base_stats->>'durability') ~ '^[1-9][0-9]*$'
                THEN (base_stats->>'durability')::integer
                ELSE NULL
            END
        ),
        break_policy = CASE
            WHEN COALESCE(
                max_durability,
                CASE
                    WHEN (base_stats->>'durability') ~ '^[1-9][0-9]*$'
                    THEN (base_stats->>'durability')::integer
                    ELSE NULL
                END
            ) IS NULL
                THEN 'indestructible'
            ELSE 'destroy_at_zero'
        END,
        base_stats = '{}'::jsonb
        """
    )
    bind.exec_driver_sql(
        """
        INSERT INTO loot_tables (channel_id, table_id, title)
        SELECT channel_id, 'lootbox_test', 'Test Lootbox Contents'
        FROM item_definitions
        WHERE item_id = 'lootbox_test'
        ON CONFLICT (channel_id, table_id) DO NOTHING
        """
    )
    bind.exec_driver_sql(
        """
        INSERT INTO loot_table_entries
            (loot_table_id, item_definition_id, weight, min_quantity, max_quantity)
        SELECT tables.id, definitions.id,
            CASE definitions.item_id
                WHEN 'rod_carbon' THEN 5000
                WHEN 'bait_magnet' THEN 3000
                WHEN 'def_electric_eel' THEN 2000
            END,
            1,
            1
        FROM loot_tables AS tables
        JOIN item_definitions AS definitions
          ON definitions.channel_id = tables.channel_id
         AND definitions.item_id IN ('rod_carbon','bait_magnet','def_electric_eel')
        WHERE tables.table_id = 'lootbox_test'
          AND NOT EXISTS (
              SELECT 1 FROM loot_table_entries AS existing
              WHERE existing.loot_table_id = tables.id
                AND existing.item_definition_id = definitions.id
          )
        """
    )
    bind.exec_driver_sql(
        """
        UPDATE item_definitions
        SET effects = '[{"type":"loot_table_roll","loot_table_id":"lootbox_test","rolls":1}]'::jsonb
        WHERE item_id = 'lootbox_test'
        """
    )


def _migrate_equipped_rods() -> None:
    op.execute(
        """
        INSERT INTO equipped_items (user_id, slot, inventory_item_id)
        SELECT users.id, 'rod', items.id
        FROM users_progress AS users
        JOIN inventory_items AS items
          ON items.user_id = users.id
         AND items.slot_id = CASE
            WHEN (users.inventory->>'equipped_rod_slot') ~ '^[0-9]+$'
            THEN (users.inventory->>'equipped_rod_slot')::integer
            ELSE NULL
         END
        ON CONFLICT DO NOTHING
        """
    )
