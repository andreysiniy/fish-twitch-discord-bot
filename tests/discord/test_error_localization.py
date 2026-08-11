from app.api.errors import ERROR_MESSAGES, EngineError, localize_error


def test_all_item_inventory_modifier_codes_are_mapped() -> None:
    for code in (
        "ITEM_NOT_FOUND",
        "ITEM_DROP_NOT_FOUND",
        "ITEM_VERSION_CONFLICT",
        "DUPLICATE_ITEM",
        "ITEM_INVALID_EFFECT",
        "INVENTORY_ITEM_NOT_FOUND",
        "INVENTORY_FULL",
        "INVENTORY_CAPACITY_CONFLICT",
        "ITEM_COMPATIBILITY",
        "PLAYER_NOT_FOUND",
        "PLAYER_MODIFIER_NOT_FOUND",
        "EVENT_REQUIRES_REVIEW",
    ):
        assert code in ERROR_MESSAGES, code


def test_localize_error_uses_mapping_and_guidance() -> None:
    error = EngineError(404, "ITEM_NOT_FOUND", "backend text", request_id="abc")
    message = localize_error(error)
    assert "Item not found" in message
    assert "abc" in message


def test_localize_error_falls_back_to_backend_text() -> None:
    error = EngineError(500, "UNKNOWN_CODE", "some backend message", request_id="r1")
    message = localize_error(error)
    assert "some backend message" in message


def test_review_error_lists_the_modifier_that_requires_review() -> None:
    error = EngineError(
        422,
        "EVENT_REQUIRES_REVIEW",
        "backend text",
        fields={
            "review_issues": [
                {
                    "message": "Good Catch is +500%, beyond the safe limit of +/- 200%."
                }
            ]
        },
        request_id="review-1",
    )

    message = localize_error(error)
    assert "Review issues:" in message
    assert "Good Catch is +500%" in message
    assert "review-1" in message
