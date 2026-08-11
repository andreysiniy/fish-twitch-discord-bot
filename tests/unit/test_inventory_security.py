import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.routes.inventory import _assert_inventory_owner, trash_item
from domain.schemas.rpg import TrashItemRequestDTO


def test_inventory_allows_owner_and_bot_service() -> None:
    _assert_inventory_owner("123", "123")
    _assert_inventory_owner("BOT_SERVICE", "123")


def test_inventory_rejects_different_jwt_subject() -> None:
    with pytest.raises(HTTPException) as error:
        _assert_inventory_owner("attacker", "victim")
    assert error.value.status_code == 403


def test_trash_requires_idempotency_key() -> None:
    http_request = Request({"type": "http", "headers": []})
    request = TrashItemRequestDTO(user_id="user", channel_id="channel", slot_id=1)

    with pytest.raises(HTTPException) as error:
        trash_item(
            request,
            http_request,
            service=object(),
            security_subject="BOT_SERVICE",
            idempotency_key=None,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Idempotency-Key is required"
