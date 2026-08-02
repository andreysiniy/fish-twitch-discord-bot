import os
from datetime import datetime, timezone

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
    AdminAuditLog,
    Channel,
    DiscordAccountLink,
    DiscordGuildBinding,
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
                modifiers={"luck_mult": "1.2", "bonus_mass": "0.15"},
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
                stat_key="positive_mass_bonus_pct",
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
        stat = explained["stats"]["positive_mass_bonus_pct"]
        assert stat["value"] == "0.25000000"
        assert stat["contributions"][0]["label"] == "Weekly promotion"

        service.set_player_modifier(
            _context("modifier-profile-luck"),
            channel.twitch_id,
            player.user_twitch_id,
            PlayerModifierSetRequest(
                stat_key="loot_luck_pct",
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
        assert profile.stats.luck_bonus == pytest.approx(0.1)

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
                        "stat": "loot_luck_pct",
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
