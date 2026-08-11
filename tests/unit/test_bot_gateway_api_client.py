from api_client import EngineApiClient


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
