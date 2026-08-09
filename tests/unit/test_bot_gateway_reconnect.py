from unittest.mock import AsyncMock, MagicMock

import pytest
from reconnect_patch import patch_reconnect_init


@pytest.mark.asyncio
async def test_patch_resets_init_before_every_connect() -> None:
    """Each (re)connect must reset the flag before delegating to twitchio."""
    connection = MagicMock()
    connection._init = True
    seen = []

    def record_init() -> None:
        seen.append(connection._init)

    original = AsyncMock(side_effect=record_init)
    connection._connect = original

    patch_reconnect_init(connection)

    await connection._connect()
    await connection._connect()

    assert seen == [False, False]
    assert original.await_count == 2


@pytest.mark.asyncio
async def test_patch_replaces_connect_handler() -> None:
    connection = MagicMock()
    connection._init = True
    original = AsyncMock()
    connection._connect = original

    patch_reconnect_init(connection)

    assert connection._connect is not original
    await connection._connect()
    original.assert_awaited_once()
    assert connection._init is False


@pytest.mark.asyncio
async def test_patch_preserves_connect_errors() -> None:
    connection = MagicMock()
    connection._init = True
    original = AsyncMock(side_effect=RuntimeError("boom"))
    connection._connect = original

    patch_reconnect_init(connection)

    with pytest.raises(RuntimeError, match="boom"):
        await connection._connect()
    assert original.await_count == 1
