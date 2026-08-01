import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from core.api_errors import ApiProblem
from infrastructure.models import IdempotencyRecord


class IdempotencyService:
    def __init__(self, db):
        self.db = db

    def execute(
        self,
        actor_scope: str,
        key: str | None,
        action: str,
        payload: dict[str, Any],
        request_id: str,
        callback: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        if not key:
            raise ApiProblem(
                400,
                "VALIDATION_ERROR",
                "Idempotency-Key is required",
                request_id=request_id,
            )
        request_hash = self._hash({"action": action, "payload": payload})
        record = (
            self.db.query(IdempotencyRecord)
            .filter(
                IdempotencyRecord.actor_scope == actor_scope,
                IdempotencyRecord.idempotency_key == key,
                IdempotencyRecord.expires_at > datetime.now(timezone.utc),
            )
            .first()
        )
        if record:
            if record.request_hash != request_hash:
                raise ApiProblem(
                    409,
                    "IDEMPOTENCY_CONFLICT",
                    "Idempotency key was used with a different payload",
                    request_id=request_id,
                )
            return dict(record.response_json)

        response = callback()
        self.db.add(
            IdempotencyRecord(
                actor_scope=actor_scope,
                idempotency_key=key,
                request_hash=request_hash,
                response_status=200,
                response_json=response,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        )
        self.db.flush()
        return response

    def _hash(self, payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()
