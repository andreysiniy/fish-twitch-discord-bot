"""Tests for the item edit flow (wizard spec §54/§55).

Covers seeding the edit draft from a backend definition with optimistic-locking
state, the shared review screen with a "Save Changes" button, the flow-based
edit idempotency key, and the ``ITEM_VERSION_CONFLICT`` recovery card that
reloads the latest version instead of overwriting it.
"""

import pytest

from app.api.errors import EngineError
from app.domain.item_ui_registry import template_for_item_type
from app.interactions.items.basic_info import BasicInfoModal
from app.interactions.items.effects import ItemEffectsView
from app.interactions.items.review import ItemReviewView, VersionConflictView
from app.interactions.items.session import ItemWizardSession, WizardStep


def _backend_item(**overrides):
    item = {
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
        "version": 4,
        "effects": [{"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.05"}],
    }
    item.update(overrides)
    return item


class FakeSessionStore:
    def __init__(self):
        self.records: dict[tuple[str, str], dict] = {}
        self.next_id = 0

    async def create(self, user_id, data):
        self.next_id += 1
        flow_id = f"flow-{self.next_id}"
        self.records[(str(user_id), flow_id)] = dict(data)
        return flow_id

    async def get(self, user_id, flow_id):
        return self.records.get((str(user_id), flow_id))

    async def update(self, user_id, flow_id, data):
        key = (str(user_id), flow_id)
        if key not in self.records:
            raise KeyError("Wizard session expired")
        self.records[key] = dict(data)

    async def delete(self, user_id, flow_id):
        self.records.pop((str(user_id), flow_id), None)


class FakeApi:
    def __init__(self, item=None):
        self.item_data = item or _backend_item()
        self.item_calls: list[str] = []
        self.upsert_calls: list[tuple[dict, str | None]] = []
        self.upsert_error: Exception | None = None

    async def item(self, interaction, item_id):
        self.item_calls.append(item_id)
        return self.item_data

    async def upsert_item(self, interaction, payload, *, idempotency_key=None):
        if self.upsert_error is not None:
            raise self.upsert_error
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

    async def send_modal(self, modal):
        self.owner.modal = modal

    async def edit_message(self, *args, **kwargs):
        self.owner.edited = kwargs

    async def defer(self, *args, **kwargs):
        self.done = True


class FakeInteraction:
    def __init__(self):
        self.response = Response(self)
        self.user = type("U", (), {"id": 1})()
        self.guild_id = 2
        self.channel_id = 3
        self.modal = None
        self.sent_message = None
        self.edited = None
        self.original_edit = None

    async def edit_original_response(self, **kwargs):
        self.original_edit = kwargs


# --- template derivation (spec §54) -----------------------------------------------


def test_template_for_item_type_maps_equipment_slots() -> None:
    assert template_for_item_type("equipment", "rod") == "fishing_rod"
    assert template_for_item_type("equipment", "bait") == "bait"
    assert template_for_item_type("equipment", "defense") == "defense"
    assert template_for_item_type("equipment", "storage") == "storage"
    assert template_for_item_type("equipment", "charm_1") == "charm"
    assert template_for_item_type("equipment", "charm_2") == "charm"


def test_template_for_item_type_maps_non_equipment() -> None:
    assert template_for_item_type("consumable") == "consumable"
    assert template_for_item_type("lootbox") == "lootbox"
    assert template_for_item_type("material") == "material"
    assert template_for_item_type("quest") == "quest"
    assert template_for_item_type("currency") == "currency"
    assert template_for_item_type("collectible") == "collectible"


def test_template_for_item_type_unknown_returns_none() -> None:
    assert template_for_item_type("hovercraft") is None


# --- edit entry point (spec §54) ---------------------------------------------------


@pytest.mark.asyncio
async def test_start_item_edit_seeds_draft_from_backend() -> None:
    from app.interactions.items.wizard import start_item_edit

    store = FakeSessionStore()
    api = FakeApi()
    interaction = FakeInteraction()

    await start_item_edit(interaction, store, api, item_id="storm_rod")

    assert isinstance(interaction.modal, BasicInfoModal)

    state = await store.get(interaction.user.id, "flow-1")
    assert state["flow_type"] == "item_edit"
    assert state["step"] == "basic_info"
    assert state["expected_version"] == 4
    assert state["template"] == "fishing_rod"
    draft = state["draft"]
    assert draft["item_id"] == "storm_rod"
    assert draft["item_type"] == "equipment"
    assert draft["equipment_slot"] == "rod"
    assert draft["max_durability"] == 150
    assert draft["break_policy"] == "unequip_broken"
    assert draft["effects"] == api.item_data["effects"]


@pytest.mark.asyncio
async def test_start_item_edit_unknown_item_propagates_engine_error() -> None:
    from app.interactions.items.wizard import start_item_edit

    store = FakeSessionStore()
    api = FakeApi()
    api.item_data = None

    async def missing(interaction, item_id):
        raise EngineError(404, "ITEM_NOT_FOUND", "Item not found in this channel.")

    api.item = missing  # type: ignore[method-assign]

    with pytest.raises(EngineError):
        await start_item_edit(FakeInteraction(), store, api, item_id="nope")


@pytest.mark.asyncio
async def test_start_effect_edit_seeds_effects_step() -> None:
    from app.interactions.items.wizard import start_effect_edit

    store = FakeSessionStore()
    api = FakeApi()
    interaction = FakeInteraction()

    await start_effect_edit(interaction, store, api, item_id="storm_rod")

    assert interaction.sent_message is not None
    view = interaction.sent_message[1].get("view")
    assert isinstance(view, ItemEffectsView)

    state = await store.get(interaction.user.id, "flow-1")
    assert state["flow_type"] == "item_edit"
    assert state["step"] == "effects"
    assert state["expected_version"] == 4
    assert state["draft"]["effects"] == api.item_data["effects"]


# --- review confirm for edit flows (spec §54) --------------------------------------


def _edit_session(store, **draft_overrides):
    draft = {
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
        "effects": [{"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.05"}],
        "expected_version": 4,
    }
    draft.update(draft_overrides)
    session = ItemWizardSession(
        store=store,
        flow_id="",
        flow_type="item_edit",
        discord_user_id="1",
        discord_guild_id="2",
        channel_id=3,
        step=WizardStep.REVIEW,
        template="fishing_rod",
        draft=draft,
        expected_version=4,
    )
    store.records[("1", "flow-1")] = session.to_redis()
    session.flow_id = "flow-1"
    return session


@pytest.mark.asyncio
async def test_edit_confirm_uses_edit_idempotency_key_and_success_message() -> None:
    from app.interactions.items.wizard import _render_review

    store = FakeSessionStore()
    session = _edit_session(store)
    api = FakeApi()

    interaction = FakeInteraction()
    await _render_review(interaction, session, api)
    assert isinstance(interaction.original_edit["view"], ItemReviewView)
    assert interaction.original_edit["view"].confirm.label == "Save Changes"

    click = FakeInteraction()
    click.response.done = True
    await interaction.original_edit["view"].confirm.callback(click)

    assert api.upsert_calls == [
        (
            {
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
                "effects": [
                    {"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.05"}
                ],
                "expected_version": 4,
            },
            "discord:item-edit:flow-1",
        )
    ]
    assert click.original_edit["content"] == "Item updated."
    assert await store.get(1, session.flow_id) is None  # draft cleaned up


@pytest.mark.asyncio
async def test_edit_review_embed_shows_expected_version_in_footer() -> None:
    from app.interactions.items.wizard import _render_review

    store = FakeSessionStore()
    session = _edit_session(store)

    interaction = FakeInteraction()
    await _render_review(interaction, session, FakeApi())

    embed = interaction.original_edit["embed"]
    assert "version 4" in embed.footer.text
    assert "schema 1" in embed.footer.text


# --- version conflict (spec §55) ----------------------------------------------------


def test_version_conflict_view_has_reload_and_cancel_buttons() -> None:
    async def noop(*args, **kwargs):
        return None

    view = VersionConflictView(initiator_id=1, on_reload=noop, on_cancel=noop)
    labels = []
    for action_row in view.to_components():
        for comp in action_row.get("components", []):
            labels.append(comp.get("label") or "")
    assert "Reload Latest Version" in labels
    assert "Cancel" in labels


def test_version_conflict_embed_explains_no_overwrite() -> None:
    async def noop(*args, **kwargs):
        return None

    view = VersionConflictView(initiator_id=1, on_reload=noop, on_cancel=noop)
    description = view.embed().description
    assert "changed by another administrator" in description
    assert "draft was not applied" in view.embed().footer.text


@pytest.mark.asyncio
async def test_version_conflict_renders_conflict_view_and_returns_to_review() -> None:
    from app.interactions.items.wizard import _render_review

    store = FakeSessionStore()
    session = _edit_session(store)
    api = FakeApi()
    api.upsert_error = EngineError(
        409, "ITEM_VERSION_CONFLICT", "Another administrator changed this item."
    )

    interaction = FakeInteraction()
    await _render_review(interaction, session, api)

    click = FakeInteraction()
    click.response.done = True
    await interaction.original_edit["view"].confirm.callback(click)

    assert isinstance(click.original_edit["view"], VersionConflictView)
    assert session.step == WizardStep.REVIEW  # flow stays open
    assert await store.get(1, session.flow_id) is not None


@pytest.mark.asyncio
async def test_reload_latest_version_refetches_and_reseeds_draft() -> None:
    from app.interactions.items.wizard import _render_review

    store = FakeSessionStore()
    session = _edit_session(store)
    api = FakeApi()
    api.upsert_error = EngineError(
        409, "ITEM_VERSION_CONFLICT", "Another administrator changed this item."
    )
    api.item_data = _backend_item(version=5, title="Storm Rod v5")

    interaction = FakeInteraction()
    await _render_review(interaction, session, api)

    click = FakeInteraction()
    click.response.done = True
    await interaction.original_edit["view"].confirm.callback(click)
    conflict_view = click.original_edit["view"]
    assert isinstance(conflict_view, VersionConflictView)

    reload_click = FakeInteraction()
    reload_click.response.done = True
    await conflict_view.reload.callback(reload_click)

    assert api.item_calls == ["storm_rod"]
    assert session.expected_version == 5
    assert session.draft["title"] == "Storm Rod v5"
    assert session.step == WizardStep.REVIEW
    # The reloaded draft re-renders the shared review card.
    assert isinstance(reload_click.original_edit["view"], ItemReviewView)
    assert await store.get(1, session.flow_id) is not None


@pytest.mark.asyncio
async def test_conflict_cancel_deletes_session() -> None:
    from app.interactions.items.wizard import _render_review

    store = FakeSessionStore()
    session = _edit_session(store)
    api = FakeApi()
    api.upsert_error = EngineError(
        409, "ITEM_VERSION_CONFLICT", "Another administrator changed this item."
    )

    interaction = FakeInteraction()
    await _render_review(interaction, session, api)

    click = FakeInteraction()
    click.response.done = True
    await interaction.original_edit["view"].confirm.callback(click)
    conflict_view = click.original_edit["view"]

    cancel_click = FakeInteraction()
    cancel_click.response.done = True
    await conflict_view.cancel.callback(cancel_click)

    assert await store.get(1, session.flow_id) is None
    assert cancel_click.edited["content"] == "Item edit cancelled."
