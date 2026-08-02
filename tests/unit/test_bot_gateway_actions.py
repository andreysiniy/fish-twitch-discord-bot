from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from action_handler import ActionHandler


@pytest.mark.asyncio
async def test_dupe_executes_extra_casts_without_recursing(monkeypatch) -> None:
    api_client = SimpleNamespace(
        fish=AsyncMock(
            return_value={
                "actions": [
                    {"type": "base_message", "action_message": "extra cast"},
                    {"type": "dupe", "amount": 20, "delay": 0},
                ]
            }
        )
    )
    bot = SimpleNamespace(api_client=api_client)
    ctx = SimpleNamespace(
        author=SimpleNamespace(
            id="123", name="angler", is_mod=False, is_subscriber=True, badges={}
        ),
        send=AsyncMock(),
    )

    async def channel_id(_ctx):
        return "456"

    monkeypatch.setattr("action_handler.get_channel_id", channel_id)

    await ActionHandler(bot).handle_engine_response(
        ctx,
        {"actions": [{"type": "dupe", "amount": 3, "delay": 0}]},
    )

    assert api_client.fish.await_count == 3
    assert ctx.send.await_count == 3
    assert api_client.fish.await_args_list[0].args[0]["bypass_cooldown"] is True
