import pytest
from fastapi import HTTPException

from api.routes.inventory import _assert_inventory_owner


def test_inventory_allows_owner_and_bot_service() -> None:
    _assert_inventory_owner("123", "123")
    _assert_inventory_owner("BOT_SERVICE", "123")


def test_inventory_rejects_different_jwt_subject() -> None:
    with pytest.raises(HTTPException) as error:
        _assert_inventory_owner("attacker", "victim")
    assert error.value.status_code == 403
