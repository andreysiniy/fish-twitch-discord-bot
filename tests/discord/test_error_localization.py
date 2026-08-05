from app.api.errors import ERROR_MESSAGES, EngineError, localize_error


def test_all_item_inventory_modifier_codes_are_mapped() -> None:
    for code in (
        "ITEM_NOT_FOUND",
        "ITEM_DROP_NOT_FOUND",
        "ITEM_VERSION_CONFLICT",
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
