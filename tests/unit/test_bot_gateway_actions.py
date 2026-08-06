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


@pytest.mark.asyncio
async def test_fish_command_passes_stable_source_request_id(monkeypatch) -> None:
    api_client = SimpleNamespace(fish=AsyncMock(return_value={"actions": []}))
    bot = SimpleNamespace(
        api_client=api_client,
        action_handler=SimpleNamespace(handle_engine_response=AsyncMock()),
    )
    from commands.fishing import FishingCog

    ctx = SimpleNamespace(
        author=SimpleNamespace(
            id="123", name="angler", is_mod=False, is_subscriber=True, badges={}
        ),
        message=SimpleNamespace(id="msg-abc123"),
        send=AsyncMock(),
    )

    async def channel_id(_ctx):  # noqa: ANN001
        return "456"

    monkeypatch.setattr("commands.fishing.get_channel_id", channel_id)

    cog = FishingCog(bot)
    fish_callback = FishingCog.fish._callback

    await fish_callback(cog, ctx)

    payload = api_client.fish.await_args.args[0]
    assert payload["source"] == "twitch"
    assert payload["source_request_id"] == "twitch-msg-abc123"

    # A second invocation with the same message id produces the same key.
    await fish_callback(cog, ctx)
    payload2 = api_client.fish.await_args.args[0]
    assert payload2["source_request_id"] == payload["source_request_id"]


@pytest.mark.asyncio
async def test_fishbag_shows_durability_and_inventory_limit() -> None:
    from commands.inventory import InventoryCog

    ctx = SimpleNamespace(send=AsyncMock())
    cog = InventoryCog(SimpleNamespace())
    await cog._send_inventory(
        ctx,
        {
            "items": [
                {
                    "slot_id": 1,
                    "equipment_slot": "rod",
                    "title": "Shit rod",
                    "quantity": 1,
                    "max_durability": 5,
                    "current_durability": 2,
                },
                {
                    "slot_id": 2,
                    "equipment_slot": "bait",
                    "title": "Bait",
                    "quantity": 7,
                    "max_durability": None,
                },
            ],
            "equipped_slots": {"rod": 1},
            "max_slots": 20,
        },
    )
    sent = ctx.send.await_args.args[0]
    assert "Inventory 2/20 slots:" in sent
    assert "[1] Shit rod x1 [EQUIPPED] (durability 2/5)" in sent
    assert "[2] Bait x7" in sent
    assert "EQUIPPED" not in sent.split("[2]")[1]


@pytest.mark.asyncio
async def test_fishbag_without_limit_still_lists_items() -> None:
    from commands.inventory import InventoryCog

    ctx = SimpleNamespace(send=AsyncMock())
    cog = InventoryCog(SimpleNamespace())
    await cog._send_inventory(
        ctx,
        {"items": [{"slot_id": 3, "title": "Rod", "quantity": 1}], "max_slots": 0},
    )
    sent = ctx.send.await_args.args[0]
    assert "[3] Rod x1" in sent
    assert "Inventory 1/0" not in sent
