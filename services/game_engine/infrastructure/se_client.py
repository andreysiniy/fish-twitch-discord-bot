"""Async StreamElements provider adapter.

The adapter deliberately exposes typed outcomes and never logs or returns
authorization material.  A single managed ``AsyncClient`` is reused by the
engine process to keep connection pooling and timeout classification stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from core.config import settings


class ProviderError(RuntimeError):
    code = "STREAM_ELEMENTS_UNAVAILABLE"
    retryable = False
    ambiguous = False
    request_sent = False

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class ProviderAuthenticationError(ProviderError):
    code = "STREAM_ELEMENTS_INVALID_CREDENTIALS"


class ProviderValidationError(ProviderError):
    code = "STREAM_ELEMENTS_UNAVAILABLE"


class ProviderRateLimitError(ProviderError):
    code = "STREAM_ELEMENTS_RATE_LIMITED"
    retryable = True


class ProviderConnectionNotSentError(ProviderError):
    code = "STREAM_ELEMENTS_UNAVAILABLE"
    retryable = True


class ProviderAmbiguousWriteError(ProviderError):
    code = "STREAM_ELEMENTS_WRITE_AMBIGUOUS"
    ambiguous = True
    request_sent = True


class ProviderServerReadError(ProviderError):
    code = "STREAM_ELEMENTS_UNAVAILABLE"
    retryable = True


class ProviderUnexpectedResponseError(ProviderError):
    code = "STREAM_ELEMENTS_UNAVAILABLE"


# Backward-compatible name used by the worker's safe retry tuple.
SETransientError = ProviderRateLimitError


@dataclass(frozen=True, slots=True)
class ProviderAdjustmentResult:
    confirmed: bool
    status_code: int
    balance_after: int | None = None
    provider_request_id: str | None = None


class SEApiClient:
    DEFAULT_BASE_URL = "https://api.streamelements.com"
    BASE_URL = f"{DEFAULT_BASE_URL}/kappa/v2/points"
    CHANNELS_ME_URL = f"{DEFAULT_BASE_URL}/kappa/v2/channels/me"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
    ):
        self._client = client
        self._owns_client = client is None
        provider_base = (base_url or settings.STREAMELEMENTS_API_BASE_URL).rstrip("/")
        self._base_url = f"{provider_base}/kappa/v2"

    async def start(self) -> None:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=3.0, read=8.0, write=5.0, pool=3.0)
            )

    async def close(self) -> None:
        if self._client is not None and self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    async def get_balance(self, se_channel_id: str, plain_token: str, username: str) -> int:
        response = await self._request(
            "GET", f"{self._base_url}/points/{se_channel_id}/{username}", plain_token
        )
        if response.status_code == 404:
            return 0
        payload = self._json(response)
        try:
            return int(payload.get("points", 0) or 0)
        except (TypeError, ValueError) as error:
            raise ProviderUnexpectedResponseError(
                "Invalid points balance response", status_code=response.status_code
            ) from error

    async def add_points(
        self,
        se_channel_id: str,
        plain_token: str,
        username: str,
        amount: int,
    ) -> ProviderAdjustmentResult:
        response = await self._request(
            "PUT",
            f"{self._base_url}/points/{se_channel_id}/{username}/{int(amount)}",
            plain_token,
            write=True,
        )
        payload = self._json(response)
        balance = payload.get("points") if isinstance(payload, dict) else None
        try:
            balance_after = int(balance) if balance is not None else None
        except (TypeError, ValueError):
            balance_after = None
        request_id = self._provider_request_id(response, payload)
        return ProviderAdjustmentResult(True, response.status_code, balance_after, request_id)

    async def get_channel_id(self, plain_token: str) -> str:
        response = await self._request("GET", f"{self._base_url}/channels/me", plain_token)
        payload = self._json(response)
        channel_id = self._extract_channel_id(payload)
        if not channel_id:
            raise ProviderUnexpectedResponseError(
                "Provider channel identity is missing", status_code=response.status_code
            )
        return channel_id

    async def _request(
        self,
        method: str,
        url: str,
        plain_token: str,
        *,
        write: bool = False,
    ) -> httpx.Response:
        await self.start()
        assert self._client is not None
        try:
            response = await self._client.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {plain_token}",
                    "Content-Type": "application/json",
                },
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as error:
            raise ProviderConnectionNotSentError(
                "Provider connection was not established"
            ) from error
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as error:
            if write:
                raise ProviderAmbiguousWriteError("Provider write outcome is unknown") from error
            raise ProviderServerReadError("Provider response could not be read") from error
        except httpx.HTTPError as error:
            if write:
                raise ProviderAmbiguousWriteError("Provider write outcome is unknown") from error
            raise ProviderServerReadError("Provider request failed") from error

        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError(
                "Provider credentials were rejected", status_code=response.status_code
            )
        if response.status_code == 429:
            raise ProviderRateLimitError(
                "Provider rate limit reached", status_code=response.status_code
            )
        if response.status_code in {400, 404}:
            raise ProviderValidationError(
                "Provider rejected the request", status_code=response.status_code
            )
        if response.status_code >= 500:
            if write:
                raise ProviderAmbiguousWriteError(
                    "Provider write outcome is unknown", status_code=response.status_code
                )
            raise ProviderServerReadError(
                "Provider service is unavailable", status_code=response.status_code
            )
        if response.status_code >= 400:
            raise ProviderUnexpectedResponseError(
                "Provider returned an unexpected response", status_code=response.status_code
            )
        return response

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except (ValueError, TypeError) as error:
            raise ProviderUnexpectedResponseError(
                "Provider returned invalid JSON", status_code=response.status_code
            ) from error
        return payload if isinstance(payload, dict) else {}

    def _provider_request_id(self, response: httpx.Response, payload: dict[str, Any]) -> str | None:
        value = (
            payload.get("requestId")
            or payload.get("request_id")
            or response.headers.get("x-request-id")
        )
        return str(value) if value else None

    def _extract_channel_id(self, payload: object) -> str | None:
        if isinstance(payload, dict):
            for key in ("_id", "id", "channel_id"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for nested in payload.values():
                nested_id = self._extract_channel_id(nested)
                if nested_id:
                    return nested_id
        elif isinstance(payload, list):
            for nested in payload:
                nested_id = self._extract_channel_id(nested)
                if nested_id:
                    return nested_id
        return None
