import httpx
import pytest
from infrastructure.se_client import (
    ProviderAmbiguousWriteError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    SEApiClient,
)


@pytest.mark.asyncio
async def test_provider_client_reuses_managed_async_session() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"points": 42})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = SEApiClient(client=client)
        assert await provider.get_balance("channel", "secret", "viewer") == 42
        assert await provider.get_balance("channel", "secret", "viewer") == 42
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, ProviderAuthenticationError), (429, ProviderRateLimitError)],
)
async def test_provider_error_classification(status, error_type) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status))
    ) as client:
        provider = SEApiClient(client=client)
        with pytest.raises(error_type):
            await provider.get_balance("channel", "secret", "viewer")


@pytest.mark.asyncio
async def test_provider_write_read_timeout_is_ambiguous() -> None:
    async def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = SEApiClient(client=client)
        with pytest.raises(ProviderAmbiguousWriteError):
            await provider.add_points("channel", "secret", "viewer", 10)
