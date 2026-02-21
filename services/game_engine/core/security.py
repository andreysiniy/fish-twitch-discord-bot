import base64
import hashlib
from datetime import datetime, timedelta
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from jose import jwt

from core.config import settings


_fernet_instance: Fernet | None = None


def create_access_token(subject: str | Any) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {
        "sub": str(subject),
        "exp": expire
    }

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
