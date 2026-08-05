import os
import uuid
from decimal import Decimal

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from core.config import settings
from infrastructure.database import Base
from infrastructure.models import (
    Channel,
    EquippedItem,
    FishingCast,
    FishingCastItemDrop,
    FishingRulesetSnapshot,
    InventoryItem,
    ItemDefinition,
    RewardPool,
    UserProgress,
)
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


@pytest.mark.integration
def test_fishing_cast_ledger_tables_upgrade_and_roundtrip() -> None:
    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"fish_ledger_{uuid.uuid4().hex[:12]}"
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
        settings.DATABASE_URL_OVERRIDE = test_url.render_as_string(hide_password=False)
        alembic_config = Config(os.path.join("services", "game_engine", "alembic.ini"))
        alembic_config.set_main_option(
            "script_location",
            os.path.abspath(os.path.join("services", "game_engine", "migrations")),
        )
        command.upgrade(alembic_config, "head")
        command.check(alembic_config)

        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {"fishing_casts", "fishing_ruleset_snapshots", "fishing_cast_item_drops"} <= tables
        assert "loot_table_entry_stock" in tables

        loot_columns = {
            column["name"] for column in inspector.get_columns("loot_table_entries")
        }
        assert {"xp_gain", "message"} <= loot_columns

        # Tenant isolation: cast is tied to its channel and user via FK constraints.
        cast_columns = {column["name"] for column in inspector.get_columns("fishing_casts")}
        assert "source_request_id" in cast_columns
        assert "rng_trace" in cast_columns
        assert "response_snapshot" in cast_columns

        with Session(engine) as db:
            channel = Channel(twitch_id=f"ledger-{uuid.uuid4().hex}", name="Ledger", config={})
            db.add(channel)
            db.flush()
            user = UserProgress(
                user_twitch_id="ledger-viewer",
                username="ledger_viewer",
                channel_id=channel.id,
                current_mass=Decimal("100.00"),
            )
            db.add(user)
            db.flush()
            snapshot = FishingRulesetSnapshot(
                channel_id=channel.id,
                ruleset_hash="a" * 64,
                channel_config_version=1,
                modifier_schema_version=2,
                engine_version="test",
            )
            db.add(snapshot)
            db.flush()
            cast = FishingCast(
                channel_id=channel.id,
                user_progress_id=user.id,
                ruleset_snapshot_id=snapshot.id,
                source="twitch",
                source_request_id="msg-1",
                status="resolved",
                twitch_user_id_snapshot="ledger-viewer",
                username_snapshot="ledger_viewer",
                location_id="default",
                mass_before=Decimal("100.00"),
                mass_after=Decimal("129.40"),
                mass_delta_applied=Decimal("29.40"),
                xp_gained=20,
                item_drop_count=1,
                reward_id="reward-fish-20pct",
                reward_type="fish",
                rng_trace=[{"stage": "ordinary_reward", "roll": "10"}],
            )
            db.add(cast)
            db.flush()
            db.add(
                FishingCastItemDrop(
                    cast_id=cast.id,
                    channel_id=channel.id,
                    item_id_snapshot="leviathan_rod",
                    title_snapshot="Leviathan Rod",
                    quantity_requested=1,
                    quantity_granted=1,
                    grant_status="granted",
                )
            )
            db.commit()

        with Session(engine) as db:
            row = db.query(FishingCast).one()
            assert row.source_request_id == "msg-1"
            assert row.ruleset_snapshot_id is not None
            assert str(row.mass_delta_applied) == "29.40"
            assert len(row.item_drops) == 1
            assert row.item_drops[0].item_id_snapshot == "leviathan_rod"

        # Idempotency: a duplicate source_request_id must be rejected by the partial unique index.
        with Session(engine) as db:
            owner = db.query(FishingCast).one()
            try:
                db.add(
                    FishingCast(
                        channel_id=owner.channel_id,
                        user_progress_id=owner.user_progress_id,
                        source="twitch",
                        source_request_id="msg-1",
                        status="resolved",
                        twitch_user_id_snapshot="ledger-viewer",
                        username_snapshot="ledger_viewer",
                        location_id="default",
                    )
                )
                db.commit()
                duplicate_rejected = False
            except Exception:
                db.rollback()
                duplicate_rejected = True
        assert duplicate_rejected is True
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
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )
        admin.close()


@pytest.mark.integration
def test_equipment_cannot_reference_another_users_inventory() -> None:
    from sqlalchemy.exc import IntegrityError

    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"fish_equip_{uuid.uuid4().hex[:12]}"
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
        settings.DATABASE_URL_OVERRIDE = test_url.render_as_string(hide_password=False)
        alembic_config = Config(os.path.join("services", "game_engine", "alembic.ini"))
        alembic_config.set_main_option(
            "script_location",
            os.path.abspath(os.path.join("services", "game_engine", "migrations")),
        )
        command.upgrade(alembic_config, "head")

        with Session(engine) as db:
            channel = Channel(twitch_id=f"equip-{uuid.uuid4().hex}", name="Equip", config={})
            db.add(channel)
            db.flush()
            user_a = UserProgress(
                user_twitch_id="owner-a", username="owner_a", channel_id=channel.id
            )
            user_b = UserProgress(
                user_twitch_id="owner-b", username="owner_b", channel_id=channel.id
            )
            db.add_all([user_a, user_b])
            db.flush()
            definition = ItemDefinition(
                channel_id=channel.id,
                item_id="rod_x",
                title="Rod X",
                type="equipment",
                slot="rod",
                rarity="common",
                stack_size=1,
            )
            db.add(definition)
            db.flush()
            db.add(
                InventoryItem(
                    user_id=user_a.id, item_id=definition.id, slot_id=1, quantity=1
                )
            )
            db.commit()
            item_id = db.query(InventoryItem).filter(InventoryItem.slot_id == 1).one().id
            owner_user_id = user_a.id
            other_user_id = user_b.id
            owner_item_id = item_id

        with Session(engine) as db:
            try:
                db.add(
                    EquippedItem(
                        user_id=other_user_id, slot="rod", inventory_item_id=owner_item_id
                    )
                )
                db.flush()
                db.rollback()
                rejected = False
            except IntegrityError:
                db.rollback()
                rejected = True
        assert rejected is True

        # Same-owner equip is permitted.
        with Session(engine) as db:
            db.add(EquippedItem(user_id=owner_user_id, slot="rod", inventory_item_id=owner_item_id))
            db.commit()
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
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )
        admin.close()


def test_economic_range_check_constraints_reject_invalid_state() -> None:
    from sqlalchemy.exc import IntegrityError

    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"fish_ck_{uuid.uuid4().hex[:12]}"
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
        settings.DATABASE_URL_OVERRIDE = test_url.render_as_string(hide_password=False)
        alembic_config = Config(os.path.join("services", "game_engine", "alembic.ini"))
        alembic_config.set_main_option(
            "script_location",
            os.path.abspath(os.path.join("services", "game_engine", "migrations")),
        )
        command.upgrade(alembic_config, "head")

        with Session(engine) as db:
            channel = Channel(twitch_id=f"ck-{uuid.uuid4().hex}", name="CK", config={})
            db.add(channel)
            db.flush()
            channel_id = channel.id
            db.commit()

        # Negative XP must be rejected by the DB.
        with Session(engine) as db:
            try:
                db.add(
                    UserProgress(
                        user_twitch_id="bad-xp",
                        username="bad_xp",
                        channel_id=channel_id,
                        level=1,
                        xp=-5,
                    )
                )
                db.flush()
                db.rollback()
                xp_rejected = False
            except IntegrityError:
                db.rollback()
                xp_rejected = True
            assert xp_rejected is True

            # Out-of-range items_drop_rate must be rejected.
            try:
                db.add(
                    RewardPool(
                        channel_id=channel_id,
                        location_id="bad-pool",
                        items_drop_rate=1.5,
                        rewards_data=[],
                        requirements={},
                    )
                )
                db.flush()
                db.rollback()
                rate_rejected = False
            except IntegrityError:
                db.rollback()
                rate_rejected = True
            assert rate_rejected is True

            # Valid state is still accepted.
            db.add(
                UserProgress(
                    user_twitch_id="good-user",
                    username="good",
                    channel_id=channel_id,
                    level=1,
                    xp=0,
                )
            )
            db.add(
                RewardPool(
                    channel_id=channel_id,
                    location_id="good-pool",
                    items_drop_rate=0.1,
                    rewards_data=[],
                    requirements={},
                )
            )
            db.commit()
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
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )
        admin.close()


def _convert_current_schema_to_legacy_snapshot(engine) -> None:
    statements = (
        "DROP TABLE inventory_item_use_records, loot_table_entry_stock, loot_table_entries, "
        "loot_tables, "
        "player_modifiers, equipped_items, idempotency_records, admin_audit_log, "
        "discord_guild_bindings, discord_account_links CASCADE",
        "ALTER TABLE channels DROP COLUMN config_version, DROP COLUMN config_updated_at",
        "ALTER TABLE reward_pools DROP COLUMN version, DROP COLUMN updated_at, "
        "DROP COLUMN item_loot_table_id",
        "ALTER TABLE fishing_events DROP COLUMN version, DROP COLUMN created_at, "
        "DROP COLUMN updated_at, DROP COLUMN status, DROP COLUMN starts_at, "
        "DROP COLUMN ends_at, DROP COLUMN activated_at, DROP COLUMN deactivated_at, "
        "DROP COLUMN modifier_schema_version, DROP COLUMN requires_review, "
        "DROP COLUMN modifiers_history",
        "ALTER TABLE users_progress DROP COLUMN base_inventory_slots",
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


@pytest.mark.integration
def test_location_items_are_migrated_into_loot_tables() -> None:
    """Upgrade a pool with legacy location_items and verify the copy end state."""
    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"fish_loot_mig_{uuid.uuid4().hex[:12]}"
    test_url = source_url.set(database=database_name)
    admin_url = source_url.set(database="postgres")
    admin = psycopg2.connect(admin_url.render_as_string(hide_password=False))
    admin.autocommit = True
    engine = None
    original_override = settings.DATABASE_URL_OVERRIDE
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}\n").format(sql.Identifier(database_name)))
        engine = create_engine(test_url)
        settings.DATABASE_URL_OVERRIDE = test_url.render_as_string(hide_password=False)
        alembic_config = Config(os.path.join("services", "game_engine", "alembic.ini"))
        alembic_config.set_main_option(
            "script_location",
            os.path.abspath(os.path.join("services", "game_engine", "migrations")),
        )
        # Upgrade to 0014 (before the location_items copy migration).
        command.upgrade(alembic_config, "20260802_0014")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO channels (twitch_id, name, is_active, config, "
                    "config_version, config_updated_at) VALUES ('mig','MIG','t','{}',1,now())"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO reward_pools (channel_id, location_id, location_name, "
                    "rewards_data, requirements, items_drop_rate) "
                    "SELECT id,'lake','Lake','[]'::jsonb,'{}'::jsonb,0.1 FROM channels "
                    "WHERE twitch_id='mig'"
                )
            )
            definition_id = connection.execute(
                text(
                    "INSERT INTO item_definitions (channel_id, item_id, title, type, "
                    "rarity, stack_size) SELECT id,'rod','Rod','equipment','rare',1 "
                    "FROM channels WHERE twitch_id='mig' RETURNING id"
                )
            ).scalar()
            pool_id = connection.execute(
                text(
                    "SELECT rp.id FROM reward_pools rp JOIN channels c ON c.id=rp.channel_id "
                    "WHERE c.twitch_id='mig'"
                )
            ).scalar()
            connection.execute(
                text(
                    "INSERT INTO location_items (reward_pool_id, item_id, weight, xp_gain, "
                    "quantity, message) VALUES (:pid,:def,100,5,10,'got {name}')"
                ),
                {"pid": pool_id, "def": definition_id},
            )
        command.upgrade(alembic_config, "head")

        with engine.connect() as connection:
            linked = connection.execute(
                text(
                    "SELECT item_loot_table_id IS NOT NULL FROM reward_pools "
                    "WHERE id = :pid"
                ),
                {"pid": pool_id},
            ).scalar()
            assert linked is True
            entries = connection.execute(
                text(
                    "SELECT count(*) FROM loot_table_entries e "
                    "JOIN loot_tables t ON e.loot_table_id = t.id "
                    "WHERE t.table_id = 'location:lake'"
                )
            ).scalar()
            assert entries == 1
            stock = connection.execute(
                text("SELECT count(*) FROM loot_table_entry_stock")
            ).scalar()
            assert stock == 1
            xp = connection.execute(
                text(
                    "SELECT e.xp_gain FROM loot_table_entries e "
                    "JOIN loot_tables t ON e.loot_table_id = t.id "
                    "WHERE t.table_id = 'location:lake'"
                )
            ).scalar()
            assert xp == 5
        command.check(alembic_config)
    finally:
        settings.DATABASE_URL_OVERRIDE = original_override
        if engine is not None:
            engine.dispose()
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}\n").format(sql.Identifier(database_name)))
        admin.close()
