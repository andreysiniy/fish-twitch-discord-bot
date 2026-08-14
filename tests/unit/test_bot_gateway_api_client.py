import asyncio

import pytest
from api_client import EngineApiClient, EngineApiError
from commands.admin import _effective_economy_switches
from commands.economy import _format_rate, _user_economy_error


def test_fish_rate_formatter_removes_insignificant_zeroes() -> None:
    assert _format_rate("120.0000") == "120"
    assert _format_rate("12.5000") == "12.5"


def test_disabled_conversions_make_buy_and_sell_effectively_unavailable() -> None:
    assert _effective_economy_switches(
        {"enabled": False, "buy_enabled": True, "sell_enabled": True}
    ) == (False, False, False)


def test_enabled_conversions_preserve_direction_switches() -> None:
    assert _effective_economy_switches(
        {"enabled": True, "buy_enabled": True, "sell_enabled": False}
    ) == (True, True, False)


def test_economy_operation_in_progress_error_is_safe_for_chat() -> None:
    error = EngineApiError(
        "Another fish sale is already processing. Please wait.",
        code="ECONOMY_OPERATION_IN_PROGRESS",
    )

    assert _user_economy_error(error) == "Another fish sale is already processing. Please wait."
    assert "Economy error" not in _user_economy_error(error)


def test_provider_error_does_not_expose_provider_name() -> None:
    error = EngineApiError("StreamElements credentials are invalid.", code="STREAM_ELEMENTS_INVALID_CREDENTIALS")

    assert _user_economy_error(error) == "The fish market is temporarily unavailable. Please try again later."


def test_review_error_formatter_includes_concrete_modifier_issue() -> None:
    client = EngineApiClient("http://engine")

    message = client._format_error_detail(
        {
            "code": "EVENT_REQUIRES_REVIEW",
            "message": "Event cannot be activated because it requires review.",
            "fields": {
                "review_issues": [
                    {"message": "Good Catch is +500%, beyond the safe limit of +/- 200%."}
                ]
            },
        }
    )

    assert "requires review" in message
    assert "Good Catch is +500%" in message


def test_error_formatter_does_not_render_unknown_json_objects() -> None:
    client = EngineApiClient("http://engine")

    message = client._format_error_detail({"error": "Bad Request", "status": 400})

    assert message == "The request could not be completed."
    assert "Bad Request" not in message


def test_error_formatter_does_not_render_json_error_strings() -> None:
    client = EngineApiClient("http://engine")

    message = client._format_error_detail('{"error":"Bad Request","status":400}')

    assert message == "The request could not be completed."


def test_error_formatter_sanitizes_nested_json_messages() -> None:
    client = EngineApiClient("http://engine")

    message = client._format_error_detail(
        [{"msg": '{"error":"Bad Request","status":400}'}]
    )

    assert message == "The request could not be completed."


@pytest.mark.asyncio
async def test_engine_timeout_is_reported_as_actionable_error() -> None:
    class TimeoutContext:
        async def __aenter__(self):
            raise asyncio.TimeoutError

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class TimeoutSession:
        closed = False

        def request(self, *args, **kwargs):
            return TimeoutContext()

    client = EngineApiClient("http://engine")
    client._session = TimeoutSession()

    with pytest.raises(EngineApiError, match="did not respond in time"):
        await client._request("POST", "/v1/fishbuy")
