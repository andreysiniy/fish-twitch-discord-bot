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
                    channel_id=channel.id,
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

        # String state/role/type CHECK constraints from the DB audit.
        string_checks = set()
        for table_name in (
            "item_definitions",
            "economy_operations",
            "outbox_events",
            "channel_access_roles",
            "admin_audit_log",
        ):
            for check in inspector.get_check_constraints(table_name):
                string_checks.add(check["name"])
        assert {
            "ck_item_definitions_type_slot",
            "ck_item_definitions_durability_policy",
            "ck_economy_operations_operation_type",
            "ck_economy_operations_state",
            "ck_outbox_events_state",
            "ck_channel_access_roles_role",
            "ck_admin_audit_log_result",
        } <= string_checks

        loot_columns = {
            column["name"] for column in inspector.get_columns("loot_table_entries")
        }
        assert {"xp_gain", "message"} <= loot_columns

        # Targeted runtime indexes from the DB audit (outbox polling, modifiers).
        runtime_indexes = set()
        for table_name in ("outbox_events", "player_modifiers"):
            runtime_indexes.update(
                index["name"] for index in inspector.get_indexes(table_name)
            )
        assert {
            "ix_outbox_pending_due",
            "ix_outbox_processing_lease",
            "ix_player_modifiers_user",
        } <= runtime_indexes

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
                    user_id=user_a.id,
                    channel_id=channel.id,
                    item_id=definition.id,
                    slot_id=1,
                    quantity=1,
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
        "DROP TABLE inventory_item_use_records, inventory_overflow_items, "
        "loot_table_entry_stock, loot_table_entries, "
        "loot_tables, "
        "player_modifiers, equipped_items, idempotency_records, admin_audit_log, "
        "discord_guild_bindings, discord_account_links, fishing_stats_daily CASCADE",
        "CREATE TABLE location_items ("
        "id SERIAL PRIMARY KEY, reward_pool_id INTEGER NOT NULL, "
        "item_id INTEGER NOT NULL, weight INTEGER NOT NULL DEFAULT 100, "
        "xp_gain INTEGER NOT NULL DEFAULT 0, quantity INTEGER, "
        "message VARCHAR DEFAULT 'You caught {name}!')",
        "ALTER TABLE channels DROP COLUMN config_version, DROP COLUMN config_updated_at",
        "ALTER TABLE reward_pools DROP COLUMN version, DROP COLUMN updated_at, "
        "DROP COLUMN item_loot_table_id",
        "ALTER TABLE fishing_events DROP COLUMN version, DROP COLUMN created_at, "
        "DROP COLUMN updated_at, DROP COLUMN status, DROP COLUMN starts_at, "
        "DROP COLUMN ends_at, DROP COLUMN activated_at, DROP COLUMN deactivated_at, "
        "DROP COLUMN modifier_schema_version, DROP COLUMN requires_review, "
        "DROP COLUMN modifiers_history",
        "ALTER TABLE users_progress DROP COLUMN base_inventory_slots, "
        "ADD COLUMN inventory JSONB DEFAULT '{\"equipped_rod_slot\": null, \"max_slots\": 20}'::jsonb",
        "ALTER TABLE inventory_items DROP COLUMN definition_version, DROP COLUMN version, "
        "DROP COLUMN current_charges",
        "ALTER TABLE fishing_casts DROP COLUMN error_message, "
        "DROP COLUMN item_drop_gate_success, DROP COLUMN item_drop_selection_success, "
        "DROP COLUMN item_drop_stock_reserved, DROP COLUMN item_drop_grant_success",
        "ALTER TABLE outbox_events DROP COLUMN lease_expires_at",
        "ALTER TABLE economy_operations DROP COLUMN compensated_at",
        "ALTER TABLE item_definitions DROP COLUMN max_durability, DROP COLUMN break_policy, "
        "DROP COLUMN effects, DROP COLUMN value, DROP COLUMN schema_version, "
        "DROP COLUMN version, DROP COLUMN is_active, DROP COLUMN archived_at, "
        "DROP COLUMN updated_at, DROP COLUMN updated_by, DROP COLUMN max_charges",
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
                    "slot, rarity, stack_size) SELECT id,'rod','Rod','equipment','rod','rare',1 "
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
                    "INSERT INTO location_items (reward_pool_id, item_id, weight, "
                    "xp_gain, quantity, message) VALUES "
                    "(:pid,:def,100,5,10,'got {name}')"
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


@pytest.mark.integration
def test_modifier_stat_keys_are_renamed_with_sign_flips() -> None:
    """Upgrade 0019 rewrites legacy stat keys and flips reduction signs."""
    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"fish_mod_v2_{uuid.uuid4().hex[:12]}"
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
        command.upgrade(alembic_config, "20260802_0018")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO channels (twitch_id, name, is_active, config, "
                    "config_version, config_updated_at) VALUES ('mod2','MOD2','t','{}',1,now())"
                )
            )
            channel_id = connection.execute(
                text("SELECT id FROM channels WHERE twitch_id='mod2'")
            ).scalar()
            user_id = connection.execute(
                text(
                    "INSERT INTO users_progress (user_twitch_id, username, channel_id, "
                    "current_mass, total_mass_stat) VALUES ('viewer','viewer',:cid,100,100) "
                    "RETURNING id"
                ),
                {"cid": channel_id},
            ).scalar()
            connection.execute(
                text(
                    "INSERT INTO player_modifiers (id, channel_id, user_progress_id, stat_key, "
                    "value, operation, scope, source_key, reason, is_enabled, "
                    "created_by_twitch_id) "
                    "VALUES (:pid,:cid,:uid,'negative_mass_reduction_pct',0.20,'add','fishing',"
                    "'promo','Legacy reduction',true,'owner')"
                ),
                {"pid": str(uuid.uuid4()), "cid": channel_id, "uid": user_id},
            )
            definition_id = connection.execute(
                text(
                    "INSERT INTO item_definitions (channel_id, item_id, title, type, "
                    "slot, rarity, stack_size, effects) SELECT id,'legacy_rod','Rod',"
                    "'equipment','rod','rare',1,CAST(:effects AS jsonb) "
                    "FROM channels WHERE twitch_id='mod2' RETURNING id"
                ),
                {
                    "effects": (
                        '[{"type":"stat_add","stat":"loot_luck_pct","value":0.05},'
                        '{"type":"stat_add","stat":"cooldown_reduction_pct","value":0.1}]'
                    )
                },
            ).scalar()
        command.upgrade(alembic_config, "head")

        with engine.connect() as connection:
            stat_key, value = connection.execute(
                text(
                    "SELECT stat_key, value FROM player_modifiers "
                    "WHERE user_progress_id = :uid"
                ),
                {"uid": user_id},
            ).one()
            assert stat_key == "negative_fish_reward_change_ratio"
            assert float(value) == pytest.approx(-0.20)
            effects = connection.execute(
                text("SELECT effects FROM item_definitions WHERE id = :did"),
                {"did": definition_id},
            ).scalar()
            assert effects[0]["stat"] == "fish_luck_change_ratio"
            assert float(effects[0]["value"]) == pytest.approx(0.05)
            assert effects[1]["stat"] == "cooldown_change_ratio"
            assert float(effects[1]["value"]) == pytest.approx(-0.1)
        command.check(alembic_config)
    finally:
        settings.DATABASE_URL_OVERRIDE = original_override
        if engine is not None:
            engine.dispose()
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}\n").format(sql.Identifier(database_name)))
        admin.close()


@pytest.mark.integration
def test_cross_channel_references_are_rejected_by_composite_fks() -> None:
    """PostgreSQL itself rejects inventory/player rows crossing channel borders."""
    from sqlalchemy.exc import IntegrityError

    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"fish_tenant_{uuid.uuid4().hex[:12]}"
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
        command.upgrade(alembic_config, "head")

        with Session(engine) as db:
            channel_a = Channel(twitch_id=f"tenant-a-{uuid.uuid4().hex[:6]}", name="A", config={})
            channel_b = Channel(twitch_id=f"tenant-b-{uuid.uuid4().hex[:6]}", name="B", config={})
            db.add_all([channel_a, channel_b])
            db.flush()
            user_a = UserProgress(
                user_twitch_id="ua", username="ua", channel_id=channel_a.id
            )
            definition_a = ItemDefinition(
                channel_id=channel_a.id,
                item_id="rod-a",
                title="Rod A",
                type="equipment",
                slot="rod",
                stack_size=1,
            )
            definition_b = ItemDefinition(
                channel_id=channel_b.id,
                item_id="rod-b",
                title="Rod B",
                type="equipment",
                slot="rod",
                stack_size=1,
            )
            db.add_all([user_a, definition_a, definition_b])
            db.flush()

            # Inventory item whose definition belongs to another channel.
            with pytest.raises(IntegrityError):
                db.add(
                    InventoryItem(
                        user_id=user_a.id,
                        channel_id=channel_a.id,
                        item_id=definition_b.id,
                        slot_id=1,
                        quantity=1,
                    )
                )
                db.flush()
            db.rollback()

            # Inventory item whose channel does not match the owner's channel.
            with pytest.raises(IntegrityError):
                db.add(
                    InventoryItem(
                        user_id=user_a.id,
                        channel_id=channel_b.id,
                        item_id=definition_a.id,
                        slot_id=1,
                        quantity=1,
                    )
                )
                db.flush()
            db.rollback()
        command.check(alembic_config)
    finally:
        settings.DATABASE_URL_OVERRIDE = original_override
        if engine is not None:
            engine.dispose()
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}\n").format(sql.Identifier(database_name)))
        admin.close()


@pytest.mark.integration
def test_new_check_constraints_reject_invalid_state() -> None:
    """Version/value/stock checks added by 0020 are enforced by the database."""
    from sqlalchemy.exc import IntegrityError

    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"fish_checks_{uuid.uuid4().hex[:12]}"
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
        command.upgrade(alembic_config, "head")

        with engine.connect() as connection:
            connection.execute(
                text(
                    "INSERT INTO channels (twitch_id, name, config, config_version, "
                    "config_updated_at) VALUES ('ck','CK','{}',1,now())"
                )
            )
            channel_id = connection.execute(
                text("SELECT id FROM channels WHERE twitch_id='ck'")
            ).scalar()
            # Negative item value rejected.
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO item_definitions (channel_id, item_id, title, type, "
                        "slot, stack_size, value) VALUES (:cid,'neg','Neg','equipment','rod',1,-5)"
                    ),
                    {"cid": channel_id},
                )
            connection.rollback()
            # Zero base inventory slots rejected.
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO users_progress (user_twitch_id, username, channel_id, "
                        "base_inventory_slots) VALUES ('u0','u0',:cid,0)"
                    ),
                    {"cid": channel_id},
                )
            connection.rollback()
            # Negative loot-table stock rejected.
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO loot_table_entry_stock "
                        "(loot_table_entry_id, remaining_quantity) VALUES (0,-1)"
                    )
                )
        command.check(alembic_config)
    finally:
        settings.DATABASE_URL_OVERRIDE = original_override
        if engine is not None:
            engine.dispose()
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}\n").format(sql.Identifier(database_name)))
        admin.close()


@pytest.mark.integration
def test_legacy_location_items_are_backfilled_into_loot_tables_then_dropped() -> None:
    """0022 preserves legacy location drops and removes the location_items table."""
    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"fish_loot_final_{uuid.uuid4().hex[:12]}"
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
        command.upgrade(alembic_config, "20260802_0021")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO channels (twitch_id, name, config, config_version, "
                    "config_updated_at) VALUES ('lootfin','LOOTFIN','{}',1,now())"
                )
            )
            channel_id = connection.execute(
                text("SELECT id FROM channels WHERE twitch_id='lootfin'")
            ).scalar()
            definition_id = connection.execute(
                text(
                    "INSERT INTO item_definitions (channel_id, item_id, title, type, "
                    "slot, stack_size) VALUES (:cid,'fin_item','Fin Item','material',"
                    "NULL,10) RETURNING id"
                ),
                {"cid": channel_id},
            ).scalar()
            pool_id = connection.execute(
                text(
                    "INSERT INTO reward_pools (channel_id, location_id, location_name, "
                    "rewards_data, requirements) VALUES (:cid,'legacy','Legacy','[]'::jsonb,"
                    "'{}'::jsonb) RETURNING id"
                ),
                {"cid": channel_id},
            ).scalar()
            connection.execute(
                text(
                    "INSERT INTO location_items (reward_pool_id, channel_id, item_id, weight, "
                    "xp_gain, quantity, message, version) VALUES "
                    "(:pool,:cid,:item,12,4,5,'Keep me',1)"
                ),
                {"pool": pool_id, "cid": channel_id, "item": definition_id},
            )
        command.upgrade(alembic_config, "head")

        with engine.connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                ).fetchall()
            }
            assert "location_items" not in tables
            pool = connection.execute(
                text(
                    "SELECT item_loot_table_id FROM reward_pools WHERE id = :pid"
                ),
                {"pid": pool_id},
            ).one()
            assert pool[0] is not None
            entry = connection.execute(
                text(
                    "SELECT e.weight, e.xp_gain, e.message, s.remaining_quantity "
                    "FROM loot_table_entries e "
                    "LEFT JOIN loot_table_entry_stock s ON s.loot_table_entry_id = e.id "
                    "WHERE e.loot_table_id = :tid AND e.item_definition_id = :iid"
                ),
                {"tid": pool[0], "iid": definition_id},
            ).one()
            assert entry[0] == 12
            assert entry[1] == 4
            assert entry[2] == "Keep me"
            assert entry[3] == 5
        command.check(alembic_config)
    finally:
        settings.DATABASE_URL_OVERRIDE = original_override
        if engine is not None:
            engine.dispose()
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}\n").format(sql.Identifier(database_name)))
        admin.close()


@pytest.mark.integration
def test_cast_trace_backfill_recovers_probability_and_roll_from_jsonb() -> None:
    """Migration 20260806_0024 backfills reward/item trace columns from JSONB."""
    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"fish_backfill_{uuid.uuid4().hex[:12]}"
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
        # Upgrade to the previous head so we can seed legacy rows.
        command.upgrade(alembic_config, "20260802_0023")

        with engine.connect() as connection:
            channel_id = connection.execute(
                text("INSERT INTO channels (twitch_id, name, config) "
                     "VALUES ('backfill-chan', 'Backfill', '{}') RETURNING id")
            ).scalar_one()
            user_id = connection.execute(
                text("INSERT INTO users_progress (user_twitch_id, username, channel_id, "
                     "current_mass, total_mass_stat) "
                     "VALUES ('bf-user', 'bf_user', :cid, 10, 10) RETURNING id"),
                {"cid": channel_id},
            ).scalar_one()
            connection.execute(
                text("INSERT INTO fishing_casts "
                     "(id, channel_id, user_progress_id, status, source, "
                     "reward_type, reward_snapshot, rng_trace, requested_at, "
                     "resolved_at, persisted_at, item_drop_succeeded, item_drop_count, "
                     "username_snapshot, twitch_user_id_snapshot, location_id) "
                     "VALUES (:id, :cid, :uid, 'resolved', 'twitch', 'fish', "
                     ":snapshot, :trace, '2026-08-01T10:00:00+00', "
                     "'2026-08-01T10:00:01+00', '2026-08-01T10:00:01+00', "
                     "FALSE, 0, 'bf_user', 'bf-user', 'default')"),
                {
                    "id": "00000000-0000-0000-0000-0000000000bf",
                    "cid": channel_id,
                    "uid": user_id,
                    "snapshot": (
                        '{"type": "fish", "weight": 1085, "reward_id": "rew-1", '
                        '"fixed_mass": "-0.1", "xp": 0}'
                    ),
                    "trace": (
                        '[{"stage": "ordinary_reward", "algorithm": "weighted_choice_v2", '
                        '"roll": "69549.296483", "total_weight": "95951", '
                        '"selected_reward_id": "rew-1", '
                        '"selected_probability": "0.011307855051"}, '
                        '{"stage": "item_drop_gate", "success": false, '
                        '"roll": "0.7463573251180865", "threshold": "0.1"}]'
                    ),
                },
            )
            connection.commit()

        command.upgrade(alembic_config, "head")
        command.check(alembic_config)

        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT reward_id, reward_weight, reward_total_weight, "
                     "reward_probability, reward_roll, "
                     "item_drop_probability, item_drop_roll, item_drop_succeeded "
                     "FROM fishing_casts WHERE id = '00000000-0000-0000-0000-0000000000bf'")
            ).one()
        assert row.reward_id == "rew-1"
        assert str(row.reward_weight) == "1085.00000000"
        assert str(row.reward_total_weight) == "95951.00000000"
        assert str(row.reward_probability) == "0.011307855051"
        assert str(row.reward_roll) == "69549.296483000000"
        assert str(row.item_drop_probability) == "0.100000000000"
        assert str(row.item_drop_roll) == "0.746357325118"
        assert row.item_drop_succeeded is False

        # Idempotency: running the same statement again changes nothing.
        with engine.connect() as connection:
            connection.execute(
                text("UPDATE fishing_casts SET reward_probability = NULL WHERE id = "
                     "'00000000-0000-0000-0000-0000000000bf'")
            )
            connection.commit()
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with engine.connect() as connection:
            ctx = MigrationContext.configure(connection)
            ops = Operations(ctx)  # noqa: F841 - reused by the backfill helper
            # Re-run backfill via the same SQL used in the migration.
            connection.execute(
                text("UPDATE fishing_casts SET reward_probability = COALESCE("
                     "reward_probability, (SELECT elem->>'selected_probability' "
                     "FROM jsonb_array_elements(rng_trace) elem "
                     "WHERE elem->>'stage' = 'ordinary_reward' LIMIT 1)::numeric) "
                     "WHERE reward_probability IS NULL AND jsonb_typeof(rng_trace) = 'array'")
            )
            connection.commit()
            restored = connection.execute(
                text("SELECT reward_probability FROM fishing_casts "
                     "WHERE id = '00000000-0000-0000-0000-0000000000bf'")
            ).scalar_one()
        assert str(restored) == "0.011307855051"
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
def test_charges_migration_renames_legacy_consume_charge_and_adds_constraints() -> None:
    """Upgrade 0026→head rewrites consume_charge to consume_durability and adds
    the charge/durability columns and CHECK constraints (spec 11.4)."""
    source_url = make_url(os.environ["DATABASE_URL"])
    database_name = f"fish_charges_mig_{uuid.uuid4().hex[:12]}"
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
        command.upgrade(alembic_config, "20260806_0026")

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO channels (twitch_id, name, config, is_active, "
                    "config_version, config_updated_at) VALUES "
                    "('charges-mig-channel', 'Charges Mig', '{}'::jsonb, true, 1, now())"
                )
            )
            channel_id = connection.execute(
                text("SELECT id FROM channels WHERE twitch_id = 'charges-mig-channel'")
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO item_definitions (channel_id, item_id, title, type, slot, "
                    "rarity, max_durability, break_policy, stack_size, effects, "
                    "schema_version, version, is_active, updated_at) VALUES "
                    "(:channel_id, 'legacy_charge_rod', 'Legacy Charge Rod', 'equipment', "
                    "'rod', 'common', 150, 'unequip_broken', 1, "
                    '\'[{"type": "consume_charge", "trigger": "after_cast", '
                    '"amount": 1}]\'::jsonb, 1, 1, true, now())'
                ),
                {"channel_id": channel_id},
            )

        command.upgrade(alembic_config, "head")
        command.check(alembic_config)

        inspector = inspect(engine)
        item_columns = {column["name"] for column in inspector.get_columns("item_definitions")}
        inventory_columns = {column["name"] for column in inspector.get_columns("inventory_items")}
        assert "max_charges" in item_columns
        assert "current_charges" in inventory_columns
        charge_checks = {
            check["name"] for check in inspector.get_check_constraints("item_definitions")
        } | {check["name"] for check in inspector.get_check_constraints("inventory_items")}
        assert {
            "ck_item_definitions_charges_consumable_only",
            "ck_item_definitions_max_charges_positive",
            "ck_item_definitions_charges_single_stack",
            "ck_item_definitions_durability_equipment_only",
            "ck_inventory_items_charges_nonnegative",
        } <= charge_checks

        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT effects FROM item_definitions WHERE item_id = 'legacy_charge_rod'")
            ).one()
            assert row.effects[0]["type"] == "consume_durability"
            assert row.effects[0]["trigger"] == "after_cast"
            assert row.effects[0]["amount"] == 1
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
