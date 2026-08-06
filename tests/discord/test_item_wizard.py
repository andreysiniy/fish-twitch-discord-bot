import pytest

import discord

from app.interactions.item_wizard import (
    build_item_payload,
    effects_preview,
)


def test_normalize_equipment_forces_slot_and_single_stack() -> None:
    payload = build_item_payload(
        {
            "item_id": "Storm_Rod",
            "title": "Storm Rod",
            "item_type": "equipment",
            "equipment_slot": "rod",
            "stack_size": 5,
            "rarity": "epic",
            "break_policy": "unequip_broken",
            "max_durability": 150,
        }
    )
    assert payload["item_id"] == "storm_rod"
    assert payload["equipment_slot"] == "rod"
    assert payload["stack_size"] == 1
    assert payload["break_policy"] == "unequip_broken"
    assert payload["max_durability"] == 150


def test_normalize_non_equipment_clears_slot_and_indestructible_durability() -> None:
    payload = build_item_payload(
        {
            "item_id": "ore",
            "title": "Ore",
            "item_type": "material",
            "equipment_slot": "rod",
            "stack_size": 10,
            "rarity": "common",
            "break_policy": "indestructible",
            "max_durability": 50,
        }
    )
    assert payload["equipment_slot"] is None
    assert payload["max_durability"] is None
    assert payload["stack_size"] == 10


def test_build_payload_carries_version_fields() -> None:
    payload = build_item_payload(
        {"item_id": "x", "title": "X", "item_type": "collectible", "rarity": "rare"},
        expected_version=3,
        schema_version=2,
    )
    assert payload["expected_version"] == 3
    assert payload["schema_version"] == 2


def test_effects_preview_human_readable() -> None:
    text = effects_preview(
        [{"type": "stat_add", "stat": "positive_fish_reward_change_ratio", "value": "0.05"}]
    )
    assert "•" in text
    assert "Positive Fish Reward" in text or "positive_fish_reward_change_ratio" in text
    assert effects_preview([]) == "No effects."


def test_item_preview_view_embed_renders() -> None:
    from app.interactions.item_wizard import ItemPreviewView

    view = ItemPreviewView(
        1,
        {
            "item_id": "storm_rod",
            "title": "Storm Rod",
            "item_type": "equipment",
            "equipment_slot": "rod",
            "rarity": "epic",
            "description": "мощная",
            "effects": [{"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.05"}],
        },
        lambda *_: None,
    )
    embed = view.embed()
    assert embed.color == discord.Color.blurple()
    assert "Effects" in {field.name for field in embed.fields}


def test_item_preview_view_has_effects_button_and_cancel_hook() -> None:
    from app.interactions.item_wizard import ItemPreviewView

    events: list[str] = []

    async def on_confirm(_interaction):  # noqa: ANN001
        events.append("confirm")

    async def on_edit_effects(_interaction):  # noqa: ANN001
        events.append("effects")

    async def on_cancel(_interaction):  # noqa: ANN001
        events.append("cancel")

    view = ItemPreviewView(
        initiator_id=1,
        draft={
            "item_id": "rod",
            "title": "Rod",
            "item_type": "equipment",
            "rarity": "rare",
            "effects": [{"type": "stat_add", "stat": "x", "value": "0.1"}],
        },
        on_confirm=on_confirm,
        on_edit_effects=on_edit_effects,
        on_cancel=on_cancel,
    )
    assert view.edit_effects.disabled is False

    # Without the effects callback the button is disabled (audit 10.1).
    plain = ItemPreviewView(
        initiator_id=1,
        draft={"item_id": "rod", "title": "Rod", "effects": []},
        on_confirm=on_confirm,
    )
    assert plain.edit_effects.disabled is True

    embed = view.embed()
    assert any(field.name == "Effects" for field in embed.fields)


@pytest.mark.asyncio
async def test_item_preview_flow_uses_generated_session_flow_id() -> None:
    """sessions.create returns the flow id; the preview flow must use it (regression:
    a previous version passed a third positional arg and crashed the command)."""
    from app.commands.items import _show_item_preview

    calls: list[tuple] = []

    class FakeSessions:
        async def create(self, user_id, data):  # noqa: ANN001
            calls.append(("create", user_id))
            return "flow-123"

        async def get(self, user_id, flow_id):  # noqa: ANN001
            calls.append(("get", user_id, flow_id))
            return {"item_id": "smth", "title": "Some item idk", "effects": []}

        async def update(self, user_id, flow_id, data):  # noqa: ANN001
            calls.append(("update", user_id, flow_id))

        async def delete(self, user_id, flow_id):  # noqa: ANN001
            calls.append(("delete", user_id, flow_id))

    class FakeInteraction:
        user = type("U", (), {"id": 1})()

        async def edit_original_response(self, **kwargs):  # noqa: ANN001
            calls.append(("edit", kwargs.get("embed").title if kwargs.get("embed") else None))

    async def mutate(confirmed, payload):  # noqa: ANN001
        calls.append(("mutate", payload["item_id"]))

    await _show_item_preview(
        interaction=FakeInteraction(),
        sessions=FakeSessions(),
        api=None,
        flow_id="flow-123",
        title="Create item: Some item idk",
        draft={"item_id": "smth", "title": "Some item idk", "effects": []},
        mutation=mutate,
        success="Item created.",
    )

    assert ("edit", "Create item: Some item idk") in calls
    # No crash, preview rendered.
    assert calls[0][0] == "edit"
