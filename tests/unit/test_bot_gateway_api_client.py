import asyncio

import pytest
from api_client import EngineApiClient, EngineApiError
from commands.economy import _user_economy_error


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
