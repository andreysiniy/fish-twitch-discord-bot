import pytest
from api.discord_dependencies import DiscordServiceContext, get_discord_service_context
from core.api_errors import ApiProblem
from core.permissions import ROLE_PERMISSIONS, ChannelPermission
from domain.schemas.discord_admin import ConfigPatchRequest, LocationCreateRequest
from main import app
from pydantic import ValidationError


def test_service_auth_uses_required_identity_context() -> None:
    context = get_discord_service_context(
        service_name="discord_gateway",
        service_api_key="test-discord-api-key",
        discord_user_id="123",
        discord_guild_id="456",
        request_id="request-1",
        idempotency_key="interaction-1:config.patch",
        can_manage_guild=True,
        management_channel_id="789",
    )

    assert context == DiscordServiceContext(
        discord_user_id="123",
        discord_guild_id="456",
        request_id="request-1",
        idempotency_key="interaction-1:config.patch",
        can_manage_guild=True,
        management_channel_id="789",
    )


def test_service_auth_rejects_invalid_credentials_and_identity() -> None:
    with pytest.raises(ApiProblem) as invalid_key:
        get_discord_service_context(
            service_name="discord_gateway",
            service_api_key="wrong",
            discord_user_id="123",
            discord_guild_id=None,
            request_id="request-1",
            idempotency_key=None,
            can_manage_guild=False,
            management_channel_id=None,
        )
    assert invalid_key.value.status_code == 401

    with pytest.raises(ApiProblem) as invalid_user:
        get_discord_service_context(
            service_name="discord_gateway",
            service_api_key="test-discord-api-key",
            discord_user_id="not-a-snowflake",
            discord_guild_id=None,
            request_id="request-1",
            idempotency_key=None,
            can_manage_guild=False,
            management_channel_id=None,
        )
    assert invalid_user.value.code == "VALIDATION_ERROR"


def test_permission_matrix_limits_moderator_and_editor_access() -> None:
    assert ChannelPermission.EVENTS_TOGGLE in ROLE_PERMISSIONS["moderator"]
    assert ChannelPermission.REWARDS_WRITE not in ROLE_PERMISSIONS["moderator"]
    assert ChannelPermission.REWARDS_WRITE in ROLE_PERMISSIONS["editor"]
    assert ChannelPermission.INTEGRATIONS_WRITE not in ROLE_PERMISSIONS["editor"]
    assert ROLE_PERMISSIONS["owner"] == set(ChannelPermission)


def test_admin_dtos_are_strict_and_bounded() -> None:
    with pytest.raises(ValidationError):
        ConfigPatchRequest(expected_version=1, changes={"fishing_cooldown": -1})
    with pytest.raises(ValidationError):
        LocationCreateRequest(location_id="Invalid ID", location_name="Lake")
    with pytest.raises(ValidationError):
        LocationCreateRequest(location_id="lake", location_name="Lake", unexpected=True)


def test_openapi_exposes_versioned_discord_admin_contract() -> None:
    paths = app.openapi()["paths"]
    expected_paths = {
        "/v1/integrations/discord/link/start",
        "/v1/integrations/discord/link/status",
        "/v1/integrations/discord/messages/placeholders",
        "/v1/integrations/discord/guilds/{guild_id}/bind",
        "/v1/admin/channels/{channel_twitch_id}/config",
        "/v1/admin/channels/{channel_twitch_id}/config/schema",
        "/v1/admin/channels/{channel_twitch_id}/messages",
        "/v1/admin/channels/{channel_twitch_id}/messages/{message_key}",
        "/v1/admin/channels/{channel_twitch_id}/locations",
        "/v1/admin/channels/{channel_twitch_id}/locations/{location_id}/rewards",
        "/v1/admin/channels/{channel_twitch_id}/locations/{location_id}/rewards/import-legacy",
        "/v1/admin/channels/{channel_twitch_id}/events/{event_id}/start",
        "/v1/admin/channels/{channel_twitch_id}/events/stop",
    }

    assert expected_paths <= paths.keys()
