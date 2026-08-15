import base64
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from jose import jwt

from core.config import settings


_fernet_instance: Fernet | None = None
_integration_fernet_instances: dict[int, Fernet] = {}


def create_access_token(subject: str | Any) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {"sub": str(subject), "exp": expire}

    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        twitch_id: str = payload.get("sub")
        return twitch_id
    except jwt.JWTError:
        return None


def encrypt_token(plain_token: str) -> str:
    if plain_token is None:
        raise ValueError("Token cannot be empty")
    normalized_token = str(plain_token).strip()
    if not normalized_token:
        raise ValueError("Token cannot be empty")
    return _get_fernet().encrypt(normalized_token.encode("utf-8")).decode("utf-8")


def decrypt_token(encrypted_token: str) -> str:
    if encrypted_token is None:
        raise ValueError("Encrypted token is empty")
    normalized_token = str(encrypted_token).strip()
    if not normalized_token:
        raise ValueError("Encrypted token is empty")
    try:
        return _get_fernet().decrypt(normalized_token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError) as error:
        raise ValueError("Failed to decrypt token") from error


def encrypt_integration_token(plain_token: str) -> str:
    """Encrypt a provider credential with the dedicated integration key."""

    if not str(plain_token or "").strip():
        raise ValueError("Token cannot be empty")
    return (
        _get_integration_fernet().encrypt(str(plain_token).strip().encode("utf-8")).decode("utf-8")
    )


def decrypt_integration_token(encrypted_token: str, *, key_version: int = 1) -> str:
    """Decrypt a provider credential, rejecting unknown key versions."""

    if key_version != settings.INTEGRATIONS_ENCRYPTION_KEY_VERSION:
        # Older keys remain decryptable during a rotation window when they
        # are explicitly supplied through INTEGRATIONS_ENCRYPTION_KEYS.
        if key_version not in _integration_key_values():
            raise ValueError("Unsupported integration credential key version")
    try:
        return (
            _get_integration_fernet(key_version)
            .decrypt(str(encrypted_token).encode("utf-8"))
            .decode("utf-8")
        )
    except (InvalidToken, ValueError) as error:
        raise ValueError("Failed to decrypt integration token") from error


def integration_key_fingerprint() -> str:
    """Return a non-secret fingerprint useful for readiness diagnostics."""

    key = settings.INTEGRATIONS_ENCRYPTION_KEY
    if not key:
        return "unconfigured"
    return hashlib.sha256(key.strip().encode("utf-8")).hexdigest()[:12]


def _get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    key = settings.ENCRYPTION_KEY
    if key:
        raw_key = key.strip().encode("utf-8")
        try:
            _fernet_instance = Fernet(raw_key)
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid ENCRYPTION_KEY") from error
        return _fernet_instance

    _fernet_instance = Fernet(_derive_fernet_key(settings.SECRET_KEY))
    return _fernet_instance


def _integration_key_values() -> dict[int, str]:
    values: dict[int, str] = {}
    current = str(settings.INTEGRATIONS_ENCRYPTION_KEY or "").strip()
    if current:
        values[settings.INTEGRATIONS_ENCRYPTION_KEY_VERSION] = current
    raw = str(settings.INTEGRATIONS_ENCRYPTION_KEYS or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid INTEGRATIONS_ENCRYPTION_KEYS") from error
        if not isinstance(parsed, dict):
            raise ValueError("Invalid INTEGRATIONS_ENCRYPTION_KEYS")
        for version, key in parsed.items():
            try:
                normalized_version = int(version)
            except (TypeError, ValueError) as error:
                raise ValueError("Invalid INTEGRATIONS_ENCRYPTION_KEYS") from error
            normalized_key = str(key or "").strip()
            if normalized_version < 1 or not normalized_key:
                raise ValueError("Invalid INTEGRATIONS_ENCRYPTION_KEYS")
            values[normalized_version] = normalized_key
    return values


def _get_integration_fernet(key_version: int | None = None) -> Fernet:
    version = key_version or settings.INTEGRATIONS_ENCRYPTION_KEY_VERSION
    cached = _integration_fernet_instances.get(version)
    if cached is not None:
        return cached
    key = _integration_key_values().get(version)
    if not key:
        raise ValueError("INTEGRATIONS_ENCRYPTION_KEY is not configured")
    try:
        instance = Fernet(key.encode("utf-8"))
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid INTEGRATIONS_ENCRYPTION_KEY") from error
    _integration_fernet_instances[version] = instance
    return instance


def _derive_fernet_key(secret: str) -> bytes:
    normalized = str(secret or "").strip()
    if not normalized:
        raise ValueError("SECRET_KEY is empty")

    secret_bytes: bytes
    if _looks_like_hex_32_bytes(normalized):
        secret_bytes = bytes.fromhex(normalized)
    else:
        secret_bytes = normalized.encode("utf-8")

    if len(secret_bytes) != 32:
        secret_bytes = hashlib.sha256(secret_bytes).digest()

    return base64.urlsafe_b64encode(secret_bytes)


def _looks_like_hex_32_bytes(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
        return True
    except ValueError:
        return False
