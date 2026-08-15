"""Authentication dependencies for least-privilege internal service APIs."""

import hmac

from core.api_errors import ApiProblem
from core.config import settings
from fastapi import Header


def require_twitch_bot_service(
    service_name: str | None = Header(None, alias="X-Service-Name"),
    service_api_key: str | None = Header(None, alias="X-Service-API-Key"),
    request_id: str | None = Header(None, alias="X-Request-ID"),
) -> None:
    expected = settings.TWITCH_BOT_SERVICE_KEY
    if (
        service_name != "bot_gateway"
        or not expected
        or not service_api_key
        or not hmac.compare_digest(service_api_key, expected)
    ):
        raise ApiProblem(
            401,
            "PERMISSION_DENIED",
            "Invalid Twitch bot service credentials",
            request_id=request_id,
        )
