import pytest
from fastapi import HTTPException

from api.routes.auth import _validate_redirect_uri


def test_oauth_redirect_allowlist() -> None:
    _validate_redirect_uri("http://localhost:5173/auth/callback")
    with pytest.raises(HTTPException):
        _validate_redirect_uri("https://attacker.example/callback")
