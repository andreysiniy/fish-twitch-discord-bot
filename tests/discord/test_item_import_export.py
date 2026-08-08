"""Tests for owner-only item JSON export/import (wizard spec §56-§58).

Covers the import payload whitelist and version mapping, the import draft
validation, the ``TWITCH_OWNER_REQUIRED`` gate on export and on the import
confirm callback, the blocking-error gate on the review embed, and the
flow-stable idempotency key derived from the slash interaction.
"""

import asyncio
import json

import pytest

from app.api.errors import EngineError
from app.commands.items import (
    _draft_from_import_payload,
    _validate_import_draft,
    register_items_group,
)
from app.commands.shared import _require_owner
from app.interactions.confirms import ConfirmView


def _export_payload():
    """A payload shaped like the backend ``item`` response (what export sends)."""
    return {
        "item_id": "storm_rod",
        "title": "Storm Rod",
        "item_type": "equipment",
        "equipment_slot": "rod",
        "rarity": "epic",
        "stack_size": 1,
        "max_durability": 150,
        "break_policy": "unequip_broken",
        "description": "A powerful rod",
        "schema_version": 1,
        "image_url": None,
        "value": None,
        "version": 7,
        "effects": [{"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.05"}],
    }


class FakeApi:
    def __init__(self, *, owner="owner-1"):
        self.owner = owner
        self.upsert_calls: list[tuple[dict, str | None]] = []
        self.status_calls = 0

    async def status(self, interaction):
        self.status_calls += 1
        return {
            "twitch": {"id": self.owner},
            "binding": {"channel_twitch_id": "owner-1"},
        }

    async def item(self, interaction, item_id):
        return _export_payload()

    async def upsert_item(self, interaction, payload, *, idempotency_key=None):
        self.upsert_calls.append((payload, idempotency_key))
        return {"ok": True}


class Response:
    def __init__(self, owner):
        self.owner = owner
        self.done = False

    def is_done(self):
        return self.done

    async def send_message(self, *args, **kwargs):
        self.owner.sent_message = (args, kwargs)

    async def defer(self, *args, **kwargs):
        self.done = True

    async def edit_message(self, *args, **kwargs):
        self.owner.edited = kwargs


class FakeInteraction:
    def __init__(self, *, owner="owner-1"):
        self.id = 42
        self.type = None
        self.user = type("U", (), {"id": 7})()
        self.response = Response(self)
        self.sent_message = None
        self.edited = None
        self.original_edit = None
        self.api_owner = owner

    async def edit_original_response(self, **kwargs):
        self.original_edit = kwargs


async def _run(interaction, command, **kwargs):
    await command.callback(interaction, **kwargs)


def _item_commands(api):
    fish = None
    items = register_items_group(None, api, None, fish)
    return items


def _sent_content(interaction) -> str:
    args, kwargs = interaction.sent_message
    content = kwargs.get("content")
    if content is None and args:
        content = args[0]
    return str(content or "")


# --- draft translation (spec §57) --------------------------------------------------


def test_draft_from_import_payload_whitelists_known_fields() -> None:
    raw = {
        "item_id": "storm_rod",
        "title": "Storm Rod",
        "item_type": "equipment",
        "rarity": "epic",
        "effects": [{"type": "grant_mass", "mass": "5"}],
        "id": 99,
        "is_active": True,
        "created_at": "2024-01-01T00:00:00Z",
    }
    draft = _draft_from_import_payload(raw)
    assert draft == {
        "item_id": "storm_rod",
        "title": "Storm Rod",
        "item_type": "equipment",
        "rarity": "epic",
        "effects": [{"type": "grant_mass", "mass": "5"}],
    }


def test_draft_from_import_payload_maps_version_to_expected_version() -> None:
    raw = {"item_id": "rod", "title": "Rod", "version": 7}
    draft = _draft_from_import_payload(raw)
    assert draft["expected_version"] == 7


def test_draft_from_import_payload_prefers_explicit_expected_version() -> None:
    raw = {"item_id": "rod", "title": "Rod", "expected_version": 3, "version": 7}
    draft = _draft_from_import_payload(raw)
    assert draft["expected_version"] == 3


def test_draft_from_import_payload_without_version_is_create() -> None:
    draft = _draft_from_import_payload({"item_id": "rod", "title": "Rod"})
    assert "expected_version" not in draft


# --- import draft validation ---------------------------------------------------------


def test_validate_import_draft_requires_item_id() -> None:
    with pytest.raises(ValueError, match="item_id"):
        _validate_import_draft({"title": "Rod"})


def test_validate_import_draft_rejects_invalid_item_id() -> None:
    with pytest.raises(ValueError, match="item_id"):
        _validate_import_draft({"item_id": "BAD ID", "title": "Rod"})


def test_validate_import_draft_requires_title() -> None:
    with pytest.raises(ValueError, match="title"):
        _validate_import_draft({"item_id": "rod"})


def test_validate_import_draft_rejects_non_list_effects() -> None:
    with pytest.raises(ValueError, match="effects"):
        _validate_import_draft({"item_id": "rod", "title": "Rod", "effects": {"a": 1}})


def test_validate_import_draft_rejects_non_dict_effect_entries() -> None:
    with pytest.raises(ValueError, match="effects"):
        _validate_import_draft(
            {"item_id": "rod", "title": "Rod", "effects": [{"mass": "5"}, "nope"]}
        )


def test_validate_import_draft_accepts_valid_draft() -> None:
    _validate_import_draft({"item_id": "rod", "title": "Rod", "effects": []})


# --- owner gate (spec §56) -----------------------------------------------------------


async def _status_payload(twitch_id, channel_twitch_id):
    class FakeApiStatus:
        async def status(self, interaction):
            return {
                "twitch": {"id": twitch_id},
                "binding": {"channel_twitch_id": channel_twitch_id},
            }

    return FakeApiStatus()


@pytest.mark.asyncio
async def test_require_owner_passes_for_channel_owner() -> None:
    api = await _status_payload("owner-1", "owner-1")
    await _require_owner(api, FakeInteraction())


@pytest.mark.asyncio
async def test_require_owner_rejects_non_owner() -> None:
    api = await _status_payload("other-user", "owner-1")
    with pytest.raises(EngineError) as excinfo:
        await _require_owner(api, FakeInteraction())
    assert excinfo.value.status == 403
    assert excinfo.value.code == "TWITCH_OWNER_REQUIRED"


@pytest.mark.asyncio
async def test_require_owner_rejects_missing_binding() -> None:
    class MissingApi:
        async def status(self, interaction):
            return {"twitch": {"id": "owner-1"}, "binding": {}}

    with pytest.raises(EngineError) as excinfo:
        await _require_owner(MissingApi(), FakeInteraction())
    assert excinfo.value.code == "TWITCH_OWNER_REQUIRED"


# --- export-json command ---------------------------------------------------------------


def _export_command(api):
    return _item_commands(api)["item_export_json"]


def test_export_json_sends_file_for_owner() -> None:
    api = FakeApi()
    command = _export_command(api)
    interaction = FakeInteraction()
    asyncio.run(_run(interaction, command, item_id="storm_rod"))

    assert interaction.sent_message is not None
    args, kwargs = interaction.sent_message
    assert kwargs.get("ephemeral") is True
    embed = kwargs.get("embed") or (args[0] if args else None)
    assert embed is not None
    assert embed.title == "Exported item"
    file = kwargs.get("file")
    assert file is not None
    assert file.filename == "storm_rod.json"
    body = file.fp.getvalue()
    assert "Storm Rod" in body
    assert '"version": 7' in body


def test_export_json_denied_for_non_owner() -> None:
    api = FakeApi(owner="other-user")
    command = _export_command(api)
    interaction = FakeInteraction()
    asyncio.run(_run(interaction, command, item_id="storm_rod"))

    assert interaction.sent_message is not None
    content = _sent_content(interaction)
    assert "owner" in content


def test_export_json_denied_for_missing_binding() -> None:
    class MissingBindingApi(FakeApi):
        async def status(self, interaction):
            return {"twitch": {"id": "owner-1"}, "binding": {}}

    api = MissingBindingApi()
    command = _export_command(api)
    interaction = FakeInteraction()
    asyncio.run(_run(interaction, command, item_id="storm_rod"))
    assert interaction.sent_message is not None
    assert "owner" in _sent_content(interaction)


# --- import-json command ---------------------------------------------------------------


def _import_command(api):
    return _item_commands(api)["item_import_json"]


def test_import_json_shows_review_and_confirm_for_owner() -> None:
    api = FakeApi()
    command = _import_command(api)
    interaction = FakeInteraction()
    payload = json.dumps(
        {
            "item_id": "storm_rod",
            "title": "Storm Rod",
            "item_type": "equipment",
            "equipment_slot": "rod",
            "rarity": "epic",
            "stack_size": 1,
            "max_durability": 150,
            "break_policy": "unequip_broken",
            "effects": [{"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.05"}],
        }
    )
    asyncio.run(_run(interaction, command, payload=payload))

    args, kwargs = interaction.sent_message
    assert kwargs.get("ephemeral") is True
    assert isinstance(kwargs["view"], ConfirmView)
    embed = args[0] if isinstance(args[0], dict) else kwargs["embed"]
    assert embed.title == "Review Item"


def test_import_json_confirm_rechecks_owner_and_uses_stable_key() -> None:
    api = FakeApi()
    command = _import_command(api)
    interaction = FakeInteraction()
    payload = json.dumps(
        {
            "item_id": "storm_rod",
            "title": "Storm Rod",
            "item_type": "equipment",
            "equipment_slot": "rod",
            "rarity": "epic",
            "stack_size": 1,
            "max_durability": 150,
            "break_policy": "unequip_broken",
            "effects": [{"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.05"}],
            "expected_version": 7,
        }
    )
    asyncio.run(_run(interaction, command, payload=payload))

    view = interaction.sent_message[1]["view"]
    assert isinstance(view, ConfirmView)

    click = FakeInteraction()
    click.response.done = True
    click.type = None
    asyncio.run(view.confirm.callback(click))

    assert len(api.upsert_calls) == 1
    payload_sent, idempotency_key = api.upsert_calls[0]
    assert idempotency_key == "discord:42:item.import"
    payload_sent = api.upsert_calls[0][0]
    assert payload_sent["item_id"] == "storm_rod"
    assert payload_sent["expected_version"] == 7
    assert click.original_edit["content"] == "Item imported."


def test_import_json_confirm_denied_when_owner_changes() -> None:
    api = FakeApi()
    command = _import_command(api)
    interaction = FakeInteraction()
    payload = json.dumps({"item_id": "rod", "title": "Rod"})
    asyncio.run(_run(interaction, command, payload=payload))

    view = interaction.sent_message[1]["view"]
    api.owner = "other-user"  # ownership changed between review and confirm
    click = FakeInteraction()
    click.response.done = True
    asyncio.run(view.confirm.callback(click))

    assert api.upsert_calls == []
    assert "owner" in click.original_edit["content"]


def test_import_json_blocks_on_compatibility_errors() -> None:
    api = FakeApi()
    command = _import_command(api)
    interaction = FakeInteraction()
    # Consumable with durability is invalid in the compatibility checker.
    payload = json.dumps(
        {
            "item_id": "rod",
            "title": "Rod",
            "item_type": "consumable",
            "max_durability": 10,
            "break_policy": "retain_broken",
            "effects": [],
        }
    )
    asyncio.run(_run(interaction, command, payload=payload))

    assert interaction.sent_message is not None
    content = _sent_content(interaction)
    assert "blocking compatibility errors" in content


def test_import_json_rejects_invalid_json() -> None:
    api = FakeApi()
    command = _import_command(api)
    interaction = FakeInteraction()
    asyncio.run(_run(interaction, command, payload="{not json"))

    assert interaction.sent_message is not None
    assert "Invalid JSON" in _sent_content(interaction)


def test_import_json_rejects_non_object_payload() -> None:
    api = FakeApi()
    command = _import_command(api)
    interaction = FakeInteraction()
    asyncio.run(_run(interaction, command, payload="[1, 2, 3]"))

    assert interaction.sent_message is not None
    assert "must be an object" in _sent_content(interaction)


def test_import_json_rejects_invalid_draft_fields() -> None:
    api = FakeApi()
    command = _import_command(api)
    interaction = FakeInteraction()
    asyncio.run(_run(interaction, command, payload=json.dumps({"title": "No id"})))

    assert interaction.sent_message is not None
    assert "item_id" in _sent_content(interaction)


def test_import_json_denied_for_non_owner() -> None:
    api = FakeApi(owner="other-user")
    command = _import_command(api)
    interaction = FakeInteraction()
    asyncio.run(_run(interaction, command, payload=json.dumps({"item_id": "rod", "title": "Rod"})))

    assert interaction.sent_message is not None
    assert "owner" in _sent_content(interaction)
    assert api.upsert_calls == []
