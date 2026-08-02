import os
import uuid

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from core.config import settings
from infrastructure.database import Base
from infrastructure.models import Channel, InventoryItem, ItemDefinition, UserProgress
from psycopg2 import sql
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_MIGRATION_TESTS") != "1",
    reason="requires PostgreSQL database creation privileges",
)


@pytest.mark.integration
def test_latest_pre_alembic_snapshot_upgrades_without_data_loss() -> None:
    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"fish_migration_{uuid.uuid4().hex[:12]}"
    test_url = source_url.set(database=database_name)
    admin_url = source_url.set(database="postgres")
    admin = psycopg2.connect(admin_url.render_as_string(hide_password=False))
    admin.autocommit = True
    engine = None
    original_override = settings.DATABASE_URL_OVERRIDE
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        engine = create_engine(test_url)
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            channel = Channel(twitch_id="legacy-channel", name="Legacy Channel", config={})
            db.add(channel)
            db.flush()
            user = UserProgress(
                user_twitch_id="legacy-viewer",
                username="legacy_viewer",
                channel_id=channel.id,
                current_mass=123,
            )
            definition = ItemDefinition(
                channel_id=channel.id,
                item_id="legacy_rod",
                title="Legacy Rod",
                type="equipment",
                slot="rod",
                rarity="rare",
                stack_size=1,
            )
            db.add_all([user, definition])
            db.flush()
            db.add(
                InventoryItem(
                    user_id=user.id,
                    item_id=definition.id,
                    slot_id=1,
                    quantity=1,
                    current_durability=4,
                )
            )
            db.commit()

        _convert_current_schema_to_legacy_snapshot(engine)
        settings.DATABASE_URL_OVERRIDE = test_url.render_as_string(hide_password=False)
        alembic_config = Config(
            os.path.join("services", "game_engine", "alembic.ini")
        )
        alembic_config.set_main_option(
            "script_location",
            os.path.abspath(os.path.join("services", "game_engine", "migrations")),
        )
        command.upgrade(alembic_config, "head")
        command.check(alembic_config)

        inspector = inspect(engine)
        item_columns = {column["name"] for column in inspector.get_columns("item_definitions")}
        assert "effects" in item_columns
        assert "sell_value" not in item_columns
        assert "is_sellable" not in item_columns
        assert "is_tradeable" not in item_columns
        assert "uq_inventory_item_user_slot" in {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("inventory_items")
        }
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT d.item_id, d.max_durability, i.current_durability, u.current_mass "
                    "FROM inventory_items i "
                    "JOIN item_definitions d ON d.id = i.item_id "
                    "JOIN users_progress u ON u.id = i.user_id"
                )
            ).one()
        assert row.item_id == "legacy_rod"
        assert row.max_durability == 7
        assert row.current_durability == 4
        assert str(row.current_mass) == "123.00"
    finally:
        settings.DATABASE_URL_OVERRIDE = original_override
        if engine is not None:
            engine.dispose()
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(database_name)
                )
            )
        admin.close()


def _convert_current_schema_to_legacy_snapshot(engine) -> None:
    statements = (
        "DROP TABLE inventory_item_use_records, loot_table_entries, loot_tables, "
        "player_modifiers, equipped_items, idempotency_records, admin_audit_log, "
        "discord_guild_bindings, discord_account_links CASCADE",
        "ALTER TABLE channels DROP COLUMN config_version, DROP COLUMN config_updated_at",
        "ALTER TABLE reward_pools DROP COLUMN version, DROP COLUMN updated_at",
        "ALTER TABLE fishing_events DROP COLUMN version, DROP COLUMN created_at, "
        "DROP COLUMN updated_at",
        "ALTER TABLE inventory_items DROP COLUMN definition_version, DROP COLUMN version",
        "ALTER TABLE location_items DROP COLUMN version, DROP COLUMN updated_at",
        "ALTER TABLE outbox_events DROP COLUMN lease_expires_at",
        "ALTER TABLE economy_operations DROP COLUMN compensated_at",
        "ALTER TABLE item_definitions DROP COLUMN max_durability, DROP COLUMN break_policy, "
        "DROP COLUMN effects, DROP COLUMN value, DROP COLUMN schema_version, "
        "DROP COLUMN version, DROP COLUMN is_active, DROP COLUMN archived_at, "
        "DROP COLUMN updated_at, DROP COLUMN updated_by",
        "ALTER TABLE item_definitions ADD COLUMN sell_value NUMERIC(18, 2), "
        "ADD COLUMN is_sellable BOOLEAN NOT NULL DEFAULT TRUE, "
        "ADD COLUMN is_tradeable BOOLEAN NOT NULL DEFAULT TRUE, "
        "ADD COLUMN durability INTEGER, "
        "ADD COLUMN base_stats JSONB NOT NULL DEFAULT '{}'::jsonb",
        "UPDATE item_definitions SET durability = 7 WHERE item_id = 'legacy_rod'",
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
