import os
from datetime import datetime, timezone

import pytest
from api.discord_dependencies import DiscordServiceContext
from core.api_errors import ApiProblem
from domain.schemas.discord_admin import (
    ConfigPatchRequest,
    DiscordEventCreateRequest,
    DiscordEventStartRequest,
    LocationCreateRequest,
    MessageTemplatePatchRequest,
    RewardCreateRequest,
)
from infrastructure.database import SessionLocal
from infrastructure.models import (
    AdminAuditLog,
    Channel,
    DiscordAccountLink,
    DiscordGuildBinding,
    RewardPool,
)
from services.discord_admin_service import DiscordAdminService

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
