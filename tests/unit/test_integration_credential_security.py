import json

import pytest
from cryptography.fernet import Fernet

import core.security as security
from core.config import settings


def test_integration_credentials_never_fall_back_to_application_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "INTEGRATIONS_ENCRYPTION_KEY", None)
    monkeypatch.setattr(settings, "INTEGRATIONS_ENCRYPTION_KEYS", None)
    security._integration_fernet_instances.clear()

    with pytest.raises(ValueError, match="INTEGRATIONS_ENCRYPTION_KEY is not configured"):
        security.encrypt_integration_token("provider-token")


def test_integration_credential_key_rotation_decrypts_previous_version(monkeypatch) -> None:
    previous_key = Fernet.generate_key().decode("ascii")
    current_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setattr(settings, "INTEGRATIONS_ENCRYPTION_KEY", current_key)
    monkeypatch.setattr(settings, "INTEGRATIONS_ENCRYPTION_KEY_VERSION", 2)
    monkeypatch.setattr(
        settings,
        "INTEGRATIONS_ENCRYPTION_KEYS",
        json.dumps({"1": previous_key, "2": current_key}),
    )
    security._integration_fernet_instances.clear()

    previous_ciphertext = Fernet(previous_key.encode("ascii")).encrypt(b"legacy-token").decode()
    assert security.decrypt_integration_token(previous_ciphertext, key_version=1) == "legacy-token"

    current_ciphertext = security.encrypt_integration_token("current-token")
    assert (
        Fernet(current_key.encode("ascii")).decrypt(current_ciphertext.encode()).decode()
        == "current-token"
    )
