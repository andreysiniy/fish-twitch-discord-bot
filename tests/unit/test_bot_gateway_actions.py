from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
async def test_fishevent_empty_duration_starts_indefinitely(monkeypatch) -> None:
    from commands.admin import AdminCog

    api_client = SimpleNamespace(
        admin_toggle_fishing_event=AsyncMock(
            return_value={
                "status": "activated",
                "event": {"id": 1, "event_title": "Lucky Event"},
                "chat_message": "",
            }
        )
    )
    bot = SimpleNamespace(api_client=api_client)
    ctx = SimpleNamespace(
        author=SimpleNamespace(id="owner-id"),
        message=SimpleNamespace(content="!fishevent 1"),
        send=AsyncMock(),
    )

    async def channel_id(_ctx):  # noqa: ANN001
        return "channel-id"

    monkeypatch.setattr("commands.admin.get_channel_id", channel_id)
    callback = AdminCog.fishevent._callback

    await callback(AdminCog(bot), ctx, "1", "")

    api_client.admin_toggle_fishing_event.assert_awaited_once_with(
        channel_id="channel-id",
        actor_twitch_id="owner-id",
        event_number=1,
        duration_seconds=None,
    )
    assert "Event enabled" in ctx.send.await_args.args[0]


@pytest.mark.asyncio
async def test_fishevent_ignores_spurious_duration_when_message_has_one_argument(
    monkeypatch,
) -> None:
    from commands.admin import AdminCog

    api_client = SimpleNamespace(
        admin_toggle_fishing_event=AsyncMock(
            return_value={
                "status": "activated",
                "event": {"id": 1, "event_title": "Lucky Event"},
                "chat_message": "",
            }
        )
    )
    bot = SimpleNamespace(api_client=api_client)
    ctx = SimpleNamespace(
        author=SimpleNamespace(id="owner-id"),
        message=SimpleNamespace(content="!fishevent 1"),
        send=AsyncMock(),
    )

    async def channel_id(_ctx):  # noqa: ANN001
        return "channel-id"

    monkeypatch.setattr("commands.admin.get_channel_id", channel_id)
    await AdminCog.fishevent._callback(AdminCog(bot), ctx, "1", "0")

    api_client.admin_toggle_fishing_event.assert_awaited_once_with(
        channel_id="channel-id",
        actor_twitch_id="owner-id",
        event_number=1,
        duration_seconds=None,
    )


@pytest.mark.asyncio
async def test_fishevent_ignores_parser_default_when_message_content_is_unavailable(
    monkeypatch,
) -> None:
    from commands.admin import AdminCog

    api_client = SimpleNamespace(
        admin_toggle_fishing_event=AsyncMock(
            return_value={
                "status": "activated",
                "event": {"id": 1, "event_title": "Lucky Event"},
                "chat_message": "",
            }
        )
    )
    bot = SimpleNamespace(api_client=api_client)
    ctx = SimpleNamespace(
        author=SimpleNamespace(id="owner-id"),
        message=SimpleNamespace(content=None),
        send=AsyncMock(),
    )

    async def channel_id(_ctx):  # noqa: ANN001
        return "channel-id"

    monkeypatch.setattr("commands.admin.get_channel_id", channel_id)
    await AdminCog.fishevent._callback(AdminCog(bot), ctx, "1", "0")

    api_client.admin_toggle_fishing_event.assert_awaited_once_with(
        channel_id="channel-id",
        actor_twitch_id="owner-id",
        event_number=1,
        duration_seconds=None,
    )


@pytest.mark.asyncio
async def test_fishevent_reads_explicit_duration_from_message_text(monkeypatch) -> None:
    from commands.admin import AdminCog

    api_client = SimpleNamespace(
        admin_toggle_fishing_event=AsyncMock(
            return_value={
                "status": "activated",
                "event": {"id": 1, "event_title": "Lucky Event"},
                "chat_message": "",
                "scheduled_disable_at": 123,
            }
        )
    )
    bot = SimpleNamespace(api_client=api_client)
    ctx = SimpleNamespace(
        author=SimpleNamespace(id="owner-id"),
        message=SimpleNamespace(content="!fishevent 1 90"),
        send=AsyncMock(),
    )

    async def channel_id(_ctx):  # noqa: ANN001
        return "channel-id"

    monkeypatch.setattr("commands.admin.get_channel_id", channel_id)
    await AdminCog.fishevent._callback(AdminCog(bot), ctx, "1", "90")

    api_client.admin_toggle_fishing_event.assert_awaited_once_with(
        channel_id="channel-id",
        actor_twitch_id="owner-id",
        event_number=1,
        duration_seconds=90,
    )


@pytest.mark.asyncio
async def test_fishevent_ignores_zero_width_placeholder_duration(monkeypatch) -> None:
    from commands.admin import AdminCog

    api_client = SimpleNamespace(
        admin_toggle_fishing_event=AsyncMock(
            return_value={
                "status": "deactivated",
                "event": {"id": 1, "event_title": "Lucky Event"},
                "chat_message": "",
            }
        )
    )
    bot = SimpleNamespace(api_client=api_client)
    ctx = SimpleNamespace(
        author=SimpleNamespace(id="owner-id"),
        message=SimpleNamespace(content="!fishevent 1 \ue000"),
        send=AsyncMock(),
    )

    async def channel_id(_ctx):  # noqa: ANN001
        return "channel-id"

    monkeypatch.setattr("commands.admin.get_channel_id", channel_id)
    await AdminCog.fishevent._callback(AdminCog(bot), ctx, "1", "\ue000")

    api_client.admin_toggle_fishing_event.assert_awaited_once_with(
        channel_id="channel-id",
        actor_twitch_id="owner-id",
        event_number=1,
        duration_seconds=None,
    )


@pytest.mark.asyncio
async def test_fishevent_treats_zero_duration_placeholder_as_indefinite(monkeypatch) -> None:
    from commands.admin import AdminCog

    api_client = SimpleNamespace(
        admin_toggle_fishing_event=AsyncMock(
            return_value={
                "status": "activated",
                "event": {"id": 1, "event_title": "Lucky Event"},
                "chat_message": "",
            }
        )
    )
    bot = SimpleNamespace(api_client=api_client)
    ctx = SimpleNamespace(
        author=SimpleNamespace(id="owner-id"),
        message=SimpleNamespace(content="!fishevent 1 0"),
        send=AsyncMock(),
    )

    async def channel_id(_ctx):  # noqa: ANN001
        return "channel-id"

    monkeypatch.setattr("commands.admin.get_channel_id", channel_id)
    await AdminCog.fishevent._callback(AdminCog(bot), ctx, "1", "0")

    api_client.admin_toggle_fishing_event.assert_awaited_once_with(
        channel_id="channel-id",
        actor_twitch_id="owner-id",
        event_number=1,
        duration_seconds=None,
    )


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


@pytest.mark.asyncio
async def test_fishbag_shows_stashed_overflow_count() -> None:
    from commands.inventory import InventoryCog

    ctx = SimpleNamespace(send=AsyncMock())
    cog = InventoryCog(SimpleNamespace())
    await cog._send_inventory(
        ctx,
        {
            "items": [{"slot_id": 1, "title": "Rod", "quantity": 1}],
            "max_slots": 20,
            "overflow_count": 5,
        },
    )
    sent = ctx.send.await_args.args[0]
    assert "Inventory 1/20 (5 stashed) slots:" in sent


def test_fishbag_argument_parser_supports_owner_slot_and_viewer_modes() -> None:
    from commands.inventory import InventoryCog

    assert InventoryCog._parse_fishbag_args(()) == (None, None, None)
    assert InventoryCog._parse_fishbag_args(("1",)) == (None, 1, None)
    assert InventoryCog._parse_fishbag_args(("@viewer",)) == ("viewer", None, None)
    assert InventoryCog._parse_fishbag_args(("viewer", "2")) == ("viewer", 2, None)
    assert InventoryCog._parse_fishbag_args(("viewer", "0"))[2]
    assert InventoryCog._parse_fishbag_args(("viewer", "slot"))[2]


@pytest.mark.asyncio
async def test_fishbag_resolves_viewer_and_requests_selected_slot(monkeypatch) -> None:
    from commands.inventory import InventoryCog

    api_client = SimpleNamespace(
        get_inventory=AsyncMock(
            return_value={
                "items": [
                    {
                        "slot_id": 2,
                        "title": "Lucky Rod",
                        "quantity": 1,
                        "item_type": "equipment",
                        "rarity": "rare",
                        "effects": [
                            {"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.10"},
                            {"type": "stat_add", "stat": "xp_gain_change_ratio", "value": "-0.20"},
                        ],
                    }
                ]
            }
        )
    )
    bot = SimpleNamespace(
        api_client=api_client,
        fetch_users=AsyncMock(return_value=[SimpleNamespace(id="target-id", name="Viewer")]),
    )
    ctx = SimpleNamespace(
        author=SimpleNamespace(id="author-id", name="Author"),
        send=AsyncMock(),
    )

    async def channel_id(_ctx):  # noqa: ANN001
        return "channel-id"

    monkeypatch.setattr("commands.inventory.get_channel_id", channel_id)
    callback = InventoryCog.fishbag._callback
    await callback(InventoryCog(bot), ctx, "@viewer", "2")

    bot.fetch_users.assert_awaited_once_with(names=["viewer"])
    api_client.get_inventory.assert_awaited_once_with(
        channel_id="channel-id", user_id="target-id"
    )
    sent = ctx.send.await_args.args[0]
    assert "Viewer's item [2] Lucky Rod" in sent
    assert "Fish Luck +10%" in sent
    assert "XP -20%" in sent


def test_fishbag_effect_formatter_preserves_integer_percentages() -> None:
    from commands.inventory import InventoryCog

    effects = InventoryCog._format_effects(
        [
            {"type": "stat_multiply", "stat": "fish_luck_change_ratio", "value": "2"},
            {"type": "block_action", "target_action_types": ["robbery"], "chance": "1"},
        ]
    )

    assert "Fish Luck +100%" in effects
    assert "Block robbery (100% chance)" in effects


@pytest.mark.asyncio
async def test_fishbag_skips_empty_effect_section() -> None:
    from commands.inventory import InventoryCog

    ctx = SimpleNamespace(send=AsyncMock())
    await InventoryCog(SimpleNamespace())._send_item_details(
        ctx,
        {
            "items": [
                {
                    "slot_id": 1,
                    "title": "Plain Bait",
                    "item_type": "consumable",
                    "rarity": "common",
                    "effects": [],
                }
            ]
        },
        slot_id=1,
    )

    sent = ctx.send.await_args.args[0]
    assert "Plain Bait" in sent
    assert "Effects:" not in sent


@pytest.mark.asyncio
async def test_fishtrash_sends_slot_and_stable_idempotency_key(monkeypatch) -> None:
    from commands.inventory import InventoryCog

    api_client = SimpleNamespace(
        trash_item=AsyncMock(
            return_value={"success": True, "message": "Discarded Old Bait x2 from slot 4."}
        )
    )
    bot = SimpleNamespace(api_client=api_client)
    ctx = SimpleNamespace(
        author=SimpleNamespace(id="author-id", name="Author"),
        message=SimpleNamespace(id="message-123"),
        send=AsyncMock(),
    )

    async def channel_id(_ctx):
        return "channel-id"

    monkeypatch.setattr("commands.inventory.get_channel_id", channel_id)
    callback = InventoryCog.fishtrash._callback
    await callback(InventoryCog(bot), ctx, "4")

    api_client.trash_item.assert_awaited_once_with(
        {
            "user_id": "author-id",
            "channel_id": "channel-id",
            "slot_id": 4,
        },
        idempotency_key="twitch-fishtrash-message-123",
    )
    assert ctx.send.await_args.args[0] == "Discarded Old Bait x2 from slot 4."


@pytest.mark.asyncio
async def test_fishtrash_rejects_invalid_slot_without_api_call() -> None:
    from commands.inventory import InventoryCog

    api_client = SimpleNamespace(trash_item=AsyncMock())
    ctx = SimpleNamespace(
        author=SimpleNamespace(id="author-id"),
        send=AsyncMock(),
    )

    await InventoryCog.fishtrash._callback(InventoryCog(SimpleNamespace(api_client=api_client)), ctx, "0")

    assert ctx.send.await_args.args[0] == "Slot must be a positive number."
    api_client.trash_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_timeout_action_without_target_user_raises_clear_error(monkeypatch) -> None:
    """A timeout action must name its target; missing target_user fails fast."""
    bot = SimpleNamespace(
        cfg=SimpleNamespace(
            twitch_token="oauth:tok",
            twitch_client_id="cid",
            bot_nick="fishdaddy",
        )
    )
    ctx = SimpleNamespace(send=AsyncMock())

    async def channel_id(_ctx):  # noqa: ANN001
        return "456"

    monkeypatch.setattr("action_handler.get_channel_id", channel_id)

    await ActionHandler(bot).handle_engine_response(
        ctx, {"actions": [{"type": "timeout", "duration": 60}]}
    )

    sent = ctx.send.await_args.args[0]
    assert "target_user" in sent
    assert "missing target_user" in sent


@pytest.mark.asyncio
async def test_timeout_api_error_includes_status_and_context(monkeypatch) -> None:
    """A Twitch API rejection is surfaced with status, body and resolved ids."""
    response = SimpleNamespace(status=403, text=AsyncMock(return_value='{"error":"Forbidden"}'))

    class _FakeResponse:
        def __init__(self, inner):
            self._inner = inner

        async def __aenter__(self):
            return self._inner

        async def __aexit__(self, *args):  # noqa: ANN002
            return False

    session = SimpleNamespace(post=MagicMock(return_value=_FakeResponse(response)))
    bot = SimpleNamespace(
        user_id="1141045443",
        cfg=SimpleNamespace(
            twitch_token="oauth:tok",
            twitch_client_id="cid",
            bot_nick="fishdaddy",
        ),
        fetch_users=AsyncMock(
            return_value=[SimpleNamespace(id="1138645097")]
        ),
    )
    ctx = SimpleNamespace(send=AsyncMock())

    async def channel_id(_ctx):  # noqa: ANN001
        return "464887139"

    monkeypatch.setattr("action_handler.get_channel_id", channel_id)
    monkeypatch.setattr(ActionHandler, "_get_session", AsyncMock(return_value=session))

    await ActionHandler(bot).handle_engine_response(
        ctx,
        {
            "actions": [
                {
                    "type": "timeout",
                    "duration": 60,
                    "reason": "fishing",
                    "target_user": "srakjopa_2",
                }
            ]
        },
    )

    sent = ctx.send.await_args.args[0]
    assert "403" in sent
    assert "Forbidden" in sent
    assert "broadcaster=464887139" in sent
    assert "moderator=1141045443" in sent
    assert "target=srakjopa_2" in sent


def _fake_session_with_responses(*responses) -> MagicMock:
    """Session whose post() returns each response in order (repeating the last)."""

    class _FakeResponse:
        def __init__(self, inner):
            self._inner = inner

        async def __aenter__(self):
            return self._inner

        async def __aexit__(self, *args):  # noqa: ANN002
            return False

    queue = list(responses)

    def _post(*_args, **_kwargs):  # noqa: ANN002, ANN003
        item = queue[0] if len(queue) == 1 else queue.pop(0)
        return _FakeResponse(item)

    session = SimpleNamespace(post=MagicMock(side_effect=_post))
    return session


def _timeout_bot_with_session(monkeypatch, session) -> tuple[object, SimpleNamespace]:
    bot = SimpleNamespace(
        user_id="1141045443",
        cfg=SimpleNamespace(
            twitch_token="oauth:tok",
            twitch_client_id="cid",
            bot_nick="fishdaddy",
        ),
        fetch_users=AsyncMock(return_value=[SimpleNamespace(id="1138645097")]),
    )
    ctx = SimpleNamespace(send=AsyncMock())

    async def channel_id(_ctx):  # noqa: ANN001
        return "464887139"

    monkeypatch.setattr("action_handler.get_channel_id", channel_id)
    monkeypatch.setattr(ActionHandler, "_get_session", AsyncMock(return_value=session))
    return bot, ctx


@pytest.mark.asyncio
async def test_timeout_retries_without_reason_when_reason_rejected(monkeypatch) -> None:
    """A moderation-rejected reason triggers a retry with the default reason."""
    rejected = SimpleNamespace(
        status=400,
        text=AsyncMock(
            return_value='{"error":"Bad Request","status":400,"message":"The user specified ban reason fails moderation standards."}'
        ),
    )
    accepted = SimpleNamespace(status=200, text=AsyncMock(return_value="{}"))
    session = _fake_session_with_responses(rejected, accepted)
    bot, ctx = _timeout_bot_with_session(monkeypatch, session)

    await ActionHandler(bot).handle_engine_response(
        ctx,
        {
            "actions": [
                {
                    "type": "timeout",
                    "duration": 60,
                    "reason": "CUNT",
                    "target_user": "srakjopa_2",
                }
            ]
        },
    )

    calls = session.post.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["json"]["data"]["reason"] == "CUNT"
    assert "reason" not in calls[1].kwargs["json"]["data"]
    warning = ctx.send.await_args.args[0]
    assert "default reason" in warning


@pytest.mark.asyncio
async def test_timeout_retry_failure_reports_retry_status(monkeypatch) -> None:
    """If the reason-less retry also fails, the retry status is surfaced."""
    rejected = SimpleNamespace(
        status=400,
        text=AsyncMock(
            return_value='{"error":"Bad Request","status":400,"message":"The user specified ban reason fails moderation standards."}'
        ),
    )
    also_failed = SimpleNamespace(
        status=500, text=AsyncMock(return_value='{"error":"Internal Server Error"}')
    )
    session = _fake_session_with_responses(rejected, also_failed)
    bot, ctx = _timeout_bot_with_session(monkeypatch, session)

    await ActionHandler(bot).handle_engine_response(
        ctx,
        {"actions": [{"type": "timeout", "duration": 60, "target_user": "srakjopa_2"}]},
    )

    sent = ctx.send.await_args.args[0]
    assert "500" in sent
    assert "Internal Server Error" in sent
