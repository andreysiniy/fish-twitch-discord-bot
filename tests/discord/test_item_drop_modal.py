import asyncio
from types import SimpleNamespace

from app.api.errors import EngineError
from app.interactions.modals import ItemDropModal


_PREVIEW = {
    "items_drop_rate": 0.1,
    "selection_weight_share": 0.5,
    "drop_probability": 0.05,
    "expected_casts_to_drop": 20.0,
    "p50": 14,
    "p90": 45,
    "expected_active_time_minutes": {"5": 100.0, "7.5": 150.0, "10": 200.0},
}


class FakeResponse:
    def __init__(self):
        self.sent = []

    async def send_message(self, content=None, **kwargs):
        self.sent.append({"content": content, **kwargs})


class FakeInteraction:
    def __init__(self):
        self.response = FakeResponse()
        self.user = SimpleNamespace(id=1)


def _modal(**kwargs):
    async def stub_preview(interaction, payload):
        return _PREVIEW

    return ItemDropModal(
        on_save=kwargs.pop("on_save", lambda interaction, payload: None),
        previewer=kwargs.pop("previewer", stub_preview),
        location_id=kwargs.pop("location_id", "abyss"),
        item_id=kwargs.pop("item_id", "leviathan_rod"),
        action=kwargs.pop("action", "Add"),
        defaults=kwargs.pop("defaults", None),
    )


def test_item_drop_modal_parses_fields() -> None:
    modal = _modal()
    modal.weight._value = "25"
    modal.xp_gain._value = "50"
    modal.quantity._value = "10"
    modal.message._value = "Got {name}!"
    assert modal._parse_payload() == {
        "item_id": "leviathan_rod",
        "weight": 25,
        "xp_gain": 50,
        "quantity": 10,
        "min_quantity": 1,
        "max_quantity": 1,
        "message": "Got {name}!",
    }


def test_item_drop_modal_empty_stock_and_message_are_unlimited() -> None:
    modal = _modal()
    modal.weight._value = "25"
    modal.xp_gain._value = "0"
    modal.quantity._value = " "
    modal.message._value = ""
    payload = modal._parse_payload()
    assert payload["quantity"] is None
    assert payload["message"] is None


def test_item_drop_modal_invalid_weight_reports_error() -> None:
    interaction = FakeInteraction()
    modal = _modal()
    modal.weight._value = "0"
    modal.xp_gain._value = "0"
    asyncio.run(modal.on_submit(interaction))
    assert "Weight must be between" in interaction.response.sent[0]["content"]


def test_item_drop_modal_non_integer_xp_reports_error() -> None:
    interaction = FakeInteraction()
    modal = _modal()
    modal.weight._value = "25"
    modal.xp_gain._value = "abc"
    asyncio.run(modal.on_submit(interaction))
    assert "XP gain must be an integer" in interaction.response.sent[0]["content"]


def test_item_drop_modal_shows_preview_and_confirms() -> None:
    saved = []

    async def on_save(interaction, payload):
        saved.append(payload)

    interaction = FakeInteraction()
    modal = _modal(on_save=on_save)
    modal.weight._value = "25"
    modal.xp_gain._value = "50"
    modal.quantity._value = ""
    modal.message._value = ""
    asyncio.run(modal.on_submit(interaction))
    sent = interaction.response.sent[0]
    assert sent["embed"].title == "Add item drop: leviathan_rod"
    asyncio.run(sent["view"].on_confirm(SimpleNamespace(id=1)))
    assert saved == [
        {
            "item_id": "leviathan_rod",
            "weight": 25,
            "xp_gain": 50,
            "quantity": None,
            "min_quantity": 1,
            "max_quantity": 1,
            "message": None,
        }
    ]


def test_item_drop_modal_edit_prefills_defaults() -> None:
    defaults = {"weight": 10, "xp_gain": 5, "quantity": 7, "message": "old", "version": 3}
    modal = _modal(action="Edit", defaults=defaults)
    assert modal.title == "Edit item drop"
    assert modal.weight.default == "10"
    assert modal.xp_gain.default == "5"
    assert modal.quantity.default == "7"
    assert modal.message.default == "old"


def test_item_drop_modal_preview_error_is_localized() -> None:
    interaction = FakeInteraction()

    async def bad_preview(interaction, payload):
        raise EngineError(422, "TEST_PREVIEW", "Item drop not found in this channel")

    modal = _modal(previewer=bad_preview)
    modal.weight._value = "25"
    modal.xp_gain._value = "0"
    asyncio.run(modal.on_submit(interaction))
    assert "Item drop not found in this channel" in interaction.response.sent[0]["content"]
