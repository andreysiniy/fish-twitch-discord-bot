import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from api.discord_dependencies import DiscordServiceContext
from core.api_errors import ApiProblem
from domain.item_schema import ModifierScope
from domain.schemas.discord_admin import (
    ConfigPatchRequest,
    DiscordEventCreateRequest,
    DiscordEventStartRequest,
    DiscordItemUpsertRequest,
    ItemDropUpsertRequest,
    LocationCreateRequest,
    MessageTemplatePatchRequest,
    PlayerItemGrantRequest,
    PlayerItemRevokeRequest,
    PlayerModifierSetRequest,
    RewardCreateRequest,
)
from infrastructure.database import SessionLocal
from infrastructure.models import (
    ItemDefinition,
    LootTable,
    LootTableEntry,
    AdminAuditLog,
    Channel,
    DiscordAccountLink,
    DiscordGuildBinding,
    FishingCast,
    RewardPool,
    UserProgress,
)
from infrastructure.repositories.channel_repo import ChannelRepository
from infrastructure.repositories.config_repo import ConfigRepository
from infrastructure.repositories.cooldown_repo import CooldownRepository
from infrastructure.repositories.user_repo import UserRepository
from services.discord_admin_service import DiscordAdminService
from services.fishing_service import FishingService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="requires PostgreSQL and Redis",
)


def _context(key: str, *, guild_id: str = "2001") -> DiscordServiceContext:
    return DiscordServiceContext(
        discord_user_id="1001",
        discord_guild_id=guild_id,
        request_id=f"request-{key}",
        idempotency_key=f"integration:{key}",
        can_manage_guild=True,
        management_channel_id="3001",
    )


@pytest.mark.integration
def test_versioned_discord_admin_workflow_is_atomic_and_audited() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        channel = Channel(twitch_id="9001", name="integration_channel", config={})
        db.add(channel)
        db.flush()
        db.add_all(
            [
                DiscordAccountLink(
                    discord_user_id="1001",
                    twitch_user_id="9001",
                    twitch_login="integration_channel",
                    verified_at=now,
                    last_verified_at=now,
                ),
                DiscordGuildBinding(
                    discord_guild_id="2001",
                    channel_id=channel.id,
                    configured_by_discord_id="1001",
                ),
                RewardPool(
                    channel_id=channel.id,
                    location_id="default",
                    location_name="Default",
                    rewards_data=[],
                    requirements={},
                ),
            ]
        )
        db.flush()
        service = DiscordAdminService(db)

        config_request = ConfigPatchRequest(
            expected_version=1,
            changes={"fishing_cooldown": 300},
        )
        first = service.patch_config(_context("config"), "9001", config_request)
        replay = service.patch_config(_context("config"), "9001", config_request)
        assert first == replay
        assert first["version"] == 2

        with pytest.raises(ApiProblem) as conflict:
            service.patch_config(
                _context("stale-config"),
                "9001",
                ConfigPatchRequest(
                    expected_version=1,
                    changes={"fishing_cooldown": 120},
                ),
            )
        assert conflict.value.code == "CONFIG_VERSION_CONFLICT"

        messages = service.get_messages(_context("messages-list"), "9001")
        assert messages["version"] == 2
        updated_message = service.patch_message(
            _context("message"),
            "9001",
            "robbery_no_target",
            MessageTemplatePatchRequest(
                expected_version=messages["version"],
                template="No available target for {attacker}.",
            ),
        )
        assert updated_message["version"] == 3
        assert channel.config["messages"]["robbery_no_target"] == (
            "No available target for {attacker}."
        )

        location = service.create_location(
            _context("location"),
            "9001",
            LocationCreateRequest(location_id="lake", location_name="Lake"),
        )
        reward = service.create_reward(
            _context("reward"),
            "9001",
            "lake",
            RewardCreateRequest(
                expected_version=location["version"],
                reward={"type": "fish", "weight": 10, "fixed_mass": "2.5"},
            ),
        )
        assert reward["reward"]["reward_id"]

        event = service.create_event(
            _context("event"),
            "9001",
            DiscordEventCreateRequest(
                event_title="Lake boost",
                override_loot_pool="lake",
                modifiers={
                    "schema_version": 2,
                    "fish_luck_change_percent": "20",
                    "positive_fish_reward_change_percent": "15",
                },
            ),
        )
        started = service.start_event(
            _context("event-start"),
            "9001",
            event["id"],
            DiscordEventStartRequest(expected_version=event["version"]),
        )
        assert started["event"]["is_active"] is True

        with pytest.raises(ApiProblem) as wrong_channel:
            service.get_config(_context("wrong-channel"), "9999")
        assert wrong_channel.value.code == "PERMISSION_DENIED"

        actions = {row.action for row in db.query(AdminAuditLog).all()}
        assert {
            "config.patch",
            "message.patch",
            "location.create",
            "reward.create",
            "event.create",
            "event.start",
        } <= actions
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_player_modifier_workflow_is_versioned_audited_and_explainable() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        channel = Channel(twitch_id="modifier-channel", name="modifier_channel", config={})
        db.add(channel)
        db.flush()
        player = UserProgress(
            user_twitch_id="modifier-player",
            username="modifier_player",
            channel_id=channel.id,
        )
        db.add_all(
            [
                player,
                DiscordAccountLink(
                    discord_user_id="1001",
                    twitch_user_id="modifier-channel",
                    twitch_login="modifier_channel",
                    verified_at=now,
                    last_verified_at=now,
                ),
                DiscordGuildBinding(
                    discord_guild_id="2001",
                    channel_id=channel.id,
                    configured_by_discord_id="1001",
                ),
            ]
        )
        db.flush()
        service = DiscordAdminService(db)
        created = service.set_player_modifier(
            _context("modifier-set"),
            channel.twitch_id,
            player.user_twitch_id,
            PlayerModifierSetRequest(
                stat_key="positive_fish_reward_change_ratio",
                operation="add",
                value="0.25",
                scope="fishing",
                source_key="promotion.weekly",
                reason="Weekly promotion",
            ),
        )
        assert created["version"] == 1

        explained = service.explain_player_stats(
            _context("modifier-explain"),
            channel.twitch_id,
            player.user_twitch_id,
            ModifierScope.FISHING,
        )
        stat = explained["stats"]["positive_fish_reward_change_ratio"]
        assert stat["value"] == "0.25000000"
        assert stat["contributions"][0]["label"] == "Weekly promotion"

        service.set_player_modifier(
            _context("modifier-profile-luck"),
            channel.twitch_id,
            player.user_twitch_id,
            PlayerModifierSetRequest(
                stat_key="fish_luck_change_ratio",
                operation="add",
                value="0.10",
                scope="fishing",
                source_key="profile.weekly",
                reason="Profile display check",
            ),
        )
        profile = FishingService(
            UserRepository(db),
            ConfigRepository(db),
            CooldownRepository(None),
            ChannelRepository(db),
        ).get_profile_stats(
            player.user_twitch_id,
            channel.twitch_id,
            player.username,
        )
        assert profile.stats.fish_luck_change_percent == pytest.approx(10)

        actions = {row.action for row in db.query(AdminAuditLog).all()}
        assert "player_modifier.set" in actions
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_item_drop_and_player_inventory_admin_workflow() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        channel = Channel(twitch_id="item-channel", name="item_channel", config={})
        db.add(channel)
        db.flush()
        player = UserProgress(
            user_twitch_id="item-player",
            username="item_player",
            channel_id=channel.id,
        )
        db.add_all(
            [
                player,
                RewardPool(
                    channel_id=channel.id,
                    location_id="default",
                    location_name="Default",
                    rewards_data=[],
                    requirements={},
                ),
                DiscordAccountLink(
                    discord_user_id="1001",
                    twitch_user_id="item-channel",
                    twitch_login="item_channel",
                    verified_at=now,
                    last_verified_at=now,
                ),
                DiscordGuildBinding(
                    discord_guild_id="2001",
                    channel_id=channel.id,
                    configured_by_discord_id="1001",
                ),
            ]
        )
        db.flush()
        service = DiscordAdminService(db)

        item = service.upsert_item(
            _context("item-create"),
            channel.twitch_id,
            DiscordItemUpsertRequest(
                item_id="discord_rod",
                title="Discord Rod",
                item_type="equipment",
                equipment_slot="rod",
                max_durability=5,
                break_policy="destroy_at_zero",
                effects=[
                    {
                        "type": "stat_add",
                        "stat": "fish_luck_change_ratio",
                        "value": "0.10",
                    }
                ],
            ),
        )
        assert item["version"] == 1

        drop = service.upsert_item_drop(
            _context("item-drop"),
            channel.twitch_id,
            "default",
            ItemDropUpsertRequest(item_id="discord_rod", weight=25, quantity=2),
        )
        assert drop["quantity"] == 2

        listed = service.list_item_drops(_context("item-drop-list"), channel.twitch_id, "default")
        assert len(listed["items"]) == 1
        listed_entry = listed["items"][0]
        assert listed_entry["selection_weight_share"] == 1.0
        assert listed_entry["drop_probability"] == pytest.approx(0.1, abs=1e-6)
        assert listed_entry["expected_casts_to_drop"] is not None

        preview = service.preview_item_drop(
            _context("item-drop-preview"), channel.twitch_id, "default", 25
        )
        assert preview["drop_probability"] == pytest.approx(0.05, abs=1e-6)
        assert preview["expected_casts_to_drop"] == pytest.approx(20.0, abs=0.1)

        grant = service.grant_player_item(
            _context("item-grant"),
            channel.twitch_id,
            player.user_twitch_id,
            PlayerItemGrantRequest(item_id="discord_rod"),
        )
        inventory_item = grant["items"][0]
        assert inventory_item["current_durability"] == 5

        revoked = service.revoke_player_item(
            _context("item-revoke"),
            channel.twitch_id,
            player.user_twitch_id,
            inventory_item["id"],
            PlayerItemRevokeRequest(quantity=1, expected_version=1),
        )
        assert revoked["remaining"] == 0

        archived = service.archive_item(
            _context("item-archive"),
            channel.twitch_id,
            "discord_rod",
            item["version"],
        )
        assert archived["is_active"] is False
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_list_loot_tables_is_tenant_scoped_and_filters_inactive() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        channel = Channel(twitch_id="loot-channel", name="loot_channel", config={})
        other = Channel(twitch_id="loot-other", name="loot_other", config={})
        db.add_all([channel, other])
        db.flush()
        db.add_all(
            [
                DiscordAccountLink(
                    discord_user_id="1001",
                    twitch_user_id="loot-channel",
                    twitch_login="loot_channel",
                    verified_at=now,
                    last_verified_at=now,
                ),
                DiscordGuildBinding(
                    discord_guild_id="2001",
                    channel_id=channel.id,
                    configured_by_discord_id="1001",
                ),
                LootTable(
                    channel_id=channel.id,
                    table_id="river_items",
                    title="River Items",
                    is_active=True,
                ),
                LootTable(
                    channel_id=channel.id,
                    table_id="lake_items",
                    title="Lake Items",
                    is_active=True,
                ),
                LootTable(
                    channel_id=channel.id,
                    table_id="retired",
                    title="Retired Pool",
                    is_active=False,
                ),
                # Belongs to another channel: must never leak across tenants.
                LootTable(
                    channel_id=other.id,
                    table_id="other_items",
                    title="Other Items",
                    is_active=True,
                ),
            ]
        )
        db.flush()
        service = DiscordAdminService(db)

        result = service.list_loot_tables(_context("loot-tables"), channel.twitch_id)
        table_ids = [entry["table_id"] for entry in result["items"]]
        assert table_ids == ["lake_items", "river_items"]
        assert all(entry["is_active"] for entry in result["items"])
        assert all("title" in entry for entry in result["items"])
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_fishing_cast_history_is_tenant_scoped_and_paginated() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        channel = Channel(twitch_id="cast-history", name="Cast History", config={})
        other = Channel(twitch_id="cast-other", name="Other", config={})
        db.add_all([channel, other])
        db.flush()
        db.add_all(
            [
                DiscordAccountLink(
                    discord_user_id="1001",
                    twitch_user_id="cast-history",
                    twitch_login="cast_history",
                    verified_at=now,
                    last_verified_at=now,
                ),
                DiscordGuildBinding(
                    discord_guild_id="2001",
                    channel_id=channel.id,
                    configured_by_discord_id="1001",
                ),
            ]
        )
        db.flush()

        user = UserProgress(
            user_twitch_id="cast-viewer",
            username="viewer",
            channel_id=channel.id,
        )
        db.add(user)
        db.flush()
        other_user = UserProgress(
            user_twitch_id="other-viewer",
            username="other_viewer",
            channel_id=other.id,
        )
        db.add(other_user)
        db.flush()

        for idx in range(3):
            db.add(
                FishingCast(
                    id=uuid.UUID(f"11111111-2222-4333-8444-{idx:012d}"),
                    channel_id=channel.id,
                    user_progress_id=user.id,
                    source="twitch",
                    status="resolved",
                    twitch_user_id_snapshot="viewer",
                    username_snapshot="viewer",
                    location_id="default",
                    mass_delta_applied=idx * 10,
                    xp_gained=5 + idx,
                    item_drop_count=1 if idx == 2 else 0,
                )
            )
        # A cast on another channel must never be visible.
        db.add(
            FishingCast(
                id=uuid.UUID("99999999-2222-4333-8444-000000000001"),
                channel_id=other.id,
                user_progress_id=other_user.id,
                source="twitch",
                status="resolved",
                twitch_user_id_snapshot="viewer",
                username_snapshot="viewer",
                location_id="default",
            )
        )
        db.flush()

        service = DiscordAdminService(db)
        page1 = service.list_recent_casts(_context("cast-list"), "cast-history", limit=2)
        assert len(page1["items"]) == 2
        assert page1["next_cursor"] is not None
        page2 = service.list_recent_casts(
            _context("cast-list-2"), "cast-history", limit=2, cursor=page1["next_cursor"]
        )
        assert len(page2["items"]) == 1
        assert page2["next_cursor"] is None
        ids = [item["cast_id"] for item in page1["items"] + page2["items"]]
        assert len(ids) == len(set(ids))
        assert not any(item_id.startswith("99999999") for item_id in ids)

        # Username filter resolves by viewer username, not by id.
        by_username = service.list_recent_casts(
            _context("cast-by-username"), "cast-history", username="viewer", limit=10
        )
        assert len(by_username["items"]) == 3
        no_match = service.list_recent_casts(
            _context("cast-no-match"), "cast-history", username="absent", limit=10
        )
        assert no_match["items"] == []

        detail = service.get_cast_detail(
            _context("cast-detail"), "cast-history", ids[0], include_technical=True
        )
        assert detail["cast_id"] == ids[0]
        assert "technical" in detail
        assert "rng_trace" in detail["technical"]

        stats = service.get_cast_summary_stats(_context("cast-stats"), "cast-history")
        assert stats["casts"] == 3
        assert stats["items_actual"] == 1

        # A cast belonging to another channel must not be reachable from this guild.
        with pytest.raises(ApiProblem) as cross:
            service.get_cast_detail(
                _context("cast-cross-other"), "cast-history", "99999999-2222-4333-8444-000000000001"
            )
        assert cross.value.code in ("PERMISSION_DENIED", "CAST_NOT_FOUND")
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_player_admin_commands_resolve_viewer_username() -> None:
    """Admin player endpoints accept the viewer's username, not just the id."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        channel = Channel(
            twitch_id=f"viewer-chan-{uuid.uuid4().hex[:8]}",
            name="Viewer Chan",
            config={},
            config_version=1,
        )
        db.add(channel)
        db.flush()
        db.add(
            DiscordAccountLink(
                discord_user_id="1001",
                twitch_user_id=channel.twitch_id,
                twitch_login=channel.name,
                verified_at=now,
                last_verified_at=now,
            )
        )
        db.add(
            DiscordGuildBinding(
                discord_guild_id="2001",
                channel_id=channel.id,
                configured_by_discord_id="1001",
                locale="en",
            )
        )
        player = UserProgress(
            user_twitch_id="2001",
            username="StreamerGuy",
            channel_id=channel.id,
            current_mass=Decimal("150.00"),
            total_mass_stat=Decimal("150.00"),
        )
        db.add(player)
        db.flush()

        service = DiscordAdminService(db)
        context = _context("viewer-username")

        # Username lookup (case-insensitive) resolves the same player.
        inventory = service.get_player_inventory_admin(
            context, channel.twitch_id, "streamerguy"
        )
        assert isinstance(inventory.get("items"), list)

        modifiers = service.list_player_modifiers(
            context, channel.twitch_id, "streamerguy"
        )
        assert modifiers["user_twitch_id"] == "2001"

        # Legacy numeric id still works as a fallback.
        inventory_by_id = service.get_player_inventory_admin(
            context, channel.twitch_id, "2001"
        )
        assert isinstance(inventory_by_id.get("items"), list)

        # Unknown viewer -> PLAYER_NOT_FOUND.
        with pytest.raises(ApiProblem) as exc_info:
            service.get_player_inventory_admin(context, channel.twitch_id, "nobody")
        assert exc_info.value.code == "PLAYER_NOT_FOUND"
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_cast_detail_rejects_malformed_and_unknown_ids_cleanly() -> None:
    """Non-UUID or unknown cast ids return CAST_NOT_FOUND, never a DataError 500."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        channel = Channel(
            twitch_id=f"cast-detail-{uuid.uuid4().hex[:8]}",
            name="Cast Detail",
            config={},
            config_version=1,
        )
        db.add(channel)
        db.flush()
        db.add(
            DiscordAccountLink(
                discord_user_id="1001",
                twitch_user_id=channel.twitch_id,
                twitch_login=channel.name,
                verified_at=now,
                last_verified_at=now,
            )
        )
        db.add(
            DiscordGuildBinding(
                discord_guild_id="2001",
                channel_id=channel.id,
                configured_by_discord_id="1001",
                locale="en",
            )
        )
        db.flush()

        service = DiscordAdminService(db)
        context = _context("cast-detail")

        # Malformed id (not a UUID) -> CAST_NOT_FOUND, not a DB DataError.
        with pytest.raises(ApiProblem) as exc_info:
            service.get_cast_detail(context, channel.twitch_id, "20")
        assert exc_info.value.code == "CAST_NOT_FOUND"
        assert exc_info.value.status_code == 404

        # Well-formed but unknown UUID -> CAST_NOT_FOUND.
        with pytest.raises(ApiProblem) as exc_info:
            service.get_cast_detail(
                context, channel.twitch_id, "00000000-0000-0000-0000-000000000000"
            )
        assert exc_info.value.code == "CAST_NOT_FOUND"
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_cast_detail_serializer_falls_back_to_jsonb_trace() -> None:
    """Detail serializer fills probability/roll from rng_trace when columns are NULL."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        channel = Channel(
            twitch_id=f"trace-fallback-{uuid.uuid4().hex[:8]}",
            name="Trace Fallback",
            config={},
            config_version=1,
        )
        db.add(channel)
        db.flush()
        db.add(
            DiscordAccountLink(
                discord_user_id="1001",
                twitch_user_id=channel.twitch_id,
                twitch_login=channel.name,
                verified_at=now,
                last_verified_at=now,
            )
        )
        db.add(
            DiscordGuildBinding(
                discord_guild_id="2001",
                channel_id=channel.id,
                configured_by_discord_id="1001",
                locale="en",
            )
        )
        user = UserProgress(
            user_twitch_id="trace-viewer",
            username="trace_viewer",
            channel_id=channel.id,
        )
        db.add(user)
        db.flush()
        cast = FishingCast(
            id=uuid.uuid4(),
            channel_id=channel.id,
            user_progress_id=user.id,
            status="resolved",
            source="twitch",
            username_snapshot="trace_viewer",
            twitch_user_id_snapshot="trace-viewer",
            location_id="default",
            reward_type="fish",
            reward_id=None,
            reward_weight=None,
            reward_total_weight=None,
            reward_probability=None,
            reward_roll=None,
            reward_snapshot={
                "type": "fish",
                "weight": 1085,
                "reward_id": "rew-legacy",
                "fixed_mass": "-0.1",
                "xp": 0,
            },
            rng_trace=[
                {
                    "stage": "ordinary_reward",
                    "algorithm": "weighted_choice_v2",
                    "roll": "69549.296483",
                    "total_weight": "95951",
                    "selected_reward_id": "rew-legacy",
                    "selected_probability": "0.011307855051",
                },
                {
                    "stage": "item_drop_gate",
                    "success": False,
                    "roll": "0.7463573251180865",
                    "threshold": "0.1",
                },
            ],
            requested_at=now,
            resolved_at=now,
            persisted_at=now,
            item_drop_succeeded=False,
            item_drop_count=0,
        )
        db.add(cast)
        db.flush()

        service = DiscordAdminService(db)
        detail = service.get_cast_detail(
            _context("trace-fallback"), channel.twitch_id, str(cast.id)
        )
        assert detail["reward"]["probability"] == "0.011307855051"
        assert detail["reward"]["roll"] == "69549.296483"
        assert detail["reward"]["weight"] == "1085"
        assert detail["reward"]["total_weight"] == "95951"
        assert detail["reward"]["reward_id"] == "rew-legacy"
        assert detail["item_drop"]["probability"] == "0.1"
        assert detail["item_drop"]["roll"] == "0.7463573251180865"
        assert detail["item_drop"]["succeeded"] is False
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_item_upsert_existing_without_version_is_clean_conflict() -> None:
    """Re-submitting an item create for an existing id is 409, not a 500."""
    from domain.schemas.discord_admin import DiscordItemUpsertRequest

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        channel = Channel(
            twitch_id=f"item-conflict-{uuid.uuid4().hex[:8]}",
            name="Item Conflict",
            config={},
            config_version=1,
        )
        db.add(channel)
        db.flush()
        db.add(
            DiscordAccountLink(
                discord_user_id="1001",
                twitch_user_id=channel.twitch_id,
                twitch_login=channel.name,
                verified_at=now,
                last_verified_at=now,
            )
        )
        db.add(
            DiscordGuildBinding(
                discord_guild_id="2001",
                channel_id=channel.id,
                configured_by_discord_id="1001",
                locale="en",
            )
        )
        db.add(
            ItemDefinition(
                channel_id=channel.id,
                item_id="existing_rod",
                title="Existing Rod",
                type="equipment",
                slot="rod",
                rarity="common",
                stack_size=1,
            )
        )
        db.flush()

        service = DiscordAdminService(db)
        context = _context("item-conflict")
        request = DiscordItemUpsertRequest(
            item_id="existing_rod",
            title="Existing Rod",
            item_type="equipment",
            rarity="common",
            equipment_slot="rod",
            stack_size=1,
            break_policy="indestructible",
            effects=[],
        )
        with pytest.raises(ApiProblem) as exc_info:
            service.upsert_item(context, channel.twitch_id, request)
        assert exc_info.value.code == "ITEM_VERSION_CONFLICT"
        assert exc_info.value.status_code == 409
    finally:
        db.rollback()
        db.close()


@pytest.mark.integration
def test_item_drop_add_existing_row_returns_item_drop_exists() -> None:
    """Adding a drop that already exists is a clear ITEM_DROP_EXISTS, not a version conflict."""
    from domain.schemas.discord_admin import ItemDropUpsertRequest

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        channel = Channel(
            twitch_id=f"drop-exists-{uuid.uuid4().hex[:8]}",
            name="Drop Exists",
            config={},
            config_version=1,
        )
        db.add(channel)
        db.flush()
        db.add(
            DiscordAccountLink(
                discord_user_id="1001",
                twitch_user_id=channel.twitch_id,
                twitch_login=channel.name,
                verified_at=now,
                last_verified_at=now,
            )
        )
        db.add(
            DiscordGuildBinding(
                discord_guild_id="2001",
                channel_id=channel.id,
                configured_by_discord_id="1001",
                locale="en",
            )
        )
        definition = ItemDefinition(
            channel_id=channel.id,
            item_id="dup_rod",
            title="Dup Rod",
            type="equipment",
            slot="rod",
            rarity="common",
            stack_size=1,
        )
        db.add(definition)
        db.flush()
        table = LootTable(channel_id=channel.id, table_id="lake_items", title="Lake Items")
        db.add(table)
        db.flush()
        pool = RewardPool(
            channel_id=channel.id,
            location_id="lake",
            items_drop_rate=0.1,
            rewards_data=[],
            requirements={},
            item_loot_table_id=table.id,
        )
        db.add(pool)
        db.flush()
        db.add(
            LootTableEntry(
                loot_table_id=table.id,
                channel_id=channel.id,
                item_definition_id=definition.id,
                weight=50,
                xp_gain=1,
            )
        )
        db.flush()

        service = DiscordAdminService(db)
        context = _context("drop-exists")
        request = ItemDropUpsertRequest(item_id="dup_rod", weight=75)
        with pytest.raises(ApiProblem) as exc_info:
            service.upsert_item_drop(context, channel.twitch_id, "lake", request)
        assert exc_info.value.code == "ITEM_DROP_EXISTS"
        assert exc_info.value.status_code == 409
    finally:
        db.rollback()
        db.close()
