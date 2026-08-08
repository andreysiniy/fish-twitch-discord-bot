"""Tests for the item creation wizard (spec §6/§8/§9/§11/§60).

Covers the template mapping, stable item ID derivation, state machine, Redis
session persistence, the type-aware mechanics view, and the final confirm flow
with the flow-based idempotency key (spec §48).
"""

import pytest

from app.domain.item_ui_registry import (
    TEMPLATES_BY_VALUE,
    slugify_item_id,
    template_to_defaults,
    validate_item_id,
)
from app.interactions.items.basic_info import BasicInfoModal
from app.interactions.items.mechanics import MechanicsView
from app.interactions.items.rarity import RarityView
from app.interactions.items.session import ItemWizardSession, WizardStep, can_transition
from app.interactions.items.template_select import TemplateSelectView


# --- template mapping (spec §8) -------------------------------------------------


def test_every_template_has_defaults() -> None:
    for template in TEMPLATES_BY_VALUE:
        defaults = template_to_defaults(template)
        assert "item_type" in defaults
        assert "stack_size" in defaults
        assert "break_policy" in defaults
        assert "max_durability" in defaults


@pytest.mark.parametrize(
    ("template", "item_type", "slot", "stack"),
    [
        ("fishing_rod", "equipment", "rod", 1),
        ("bait", "equipment", "bait", 1),
        ("defense", "equipment", "defense", 1),
        ("storage", "equipment", "storage", 1),
        ("charm", "equipment", None, 1),
        ("consumable", "consumable", None, 20),
        ("lootbox", "lootbox", None, 20),
        ("material", "material", None, 100),
        ("quest", "quest", None, 1),
        ("currency", "currency", None, 1000),
        ("collectible", "collectible", None, 1),
    ],
)
def test_template_to_defaults(template, item_type, slot, stack) -> None:
    defaults = template_to_defaults(template)
    assert defaults["item_type"] == item_type
    assert defaults["equipment_slot"] == slot
    assert defaults["stack_size"] == stack
    assert defaults["break_policy"] == "indestructible"


# --- stable item id (spec §9.2) --------------------------------------------------


def test_slugify_display_name() -> None:
    assert slugify_item_id("Storm Rod") == "storm_rod"
    assert slugify_item_id("  Moon   Stone  ") == "moon_stone"
    assert slugify_item_id("Ore-2") == "ore-2"


def test_slugify_unusable_name_returns_none() -> None:
    assert slugify_item_id("!!!") is None
    assert slugify_item_id("") is None


def test_validate_item_id() -> None:
    assert validate_item_id("storm_rod") is True
    assert validate_item_id("Storm-Rod") is True  # case-insensitive, lowercased
    assert validate_item_id("1leading_digit_ok") is True
    assert validate_item_id("-leading dash") is False
    assert validate_item_id("1leading digit ok") is False  # spaces are invalid
    assert validate_item_id("has space") is False


# --- state machine (spec §60) ----------------------------------------------------


def test_state_machine_allows_forward_and_back_transitions() -> None:
    assert can_transition(WizardStep.TEMPLATE, WizardStep.BASIC_INFO)
    assert can_transition(WizardStep.BASIC_INFO, WizardStep.RARITY)
    assert can_transition(WizardStep.RARITY, WizardStep.MECHANICS)
    assert can_transition(WizardStep.MECHANICS, WizardStep.EFFECTS)
    assert can_transition(WizardStep.EFFECTS, WizardStep.REVIEW)
    assert can_transition(WizardStep.REVIEW, WizardStep.SUBMITTING)
    assert can_transition(WizardStep.MECHANICS, WizardStep.RARITY)  # back
    assert can_transition(WizardStep.BASIC_INFO, WizardStep.TEMPLATE)  # back


def test_state_machine_forbids_skips_and_reentry() -> None:
    assert not can_transition(WizardStep.TEMPLATE, WizardStep.REVIEW)
    assert not can_transition(WizardStep.TEMPLATE, WizardStep.SUBMITTING)
    assert not can_transition(WizardStep.REVIEW, WizardStep.TEMPLATE)
    assert not can_transition(WizardStep.DONE, WizardStep.REVIEW)


# --- session persistence (spec §41/§42) -------------------------------------------


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


@pytest.mark.asyncio
async def test_session_roundtrip_via_store() -> None:
    store = FakeSessionStore()
    session = await ItemWizardSession.create(
        store,
        flow_type="item_create",
        discord_user_id=123,
        discord_guild_id=456,
        channel_id=789,
        template="consumable",
    )
    assert session.step == WizardStep.TEMPLATE
    assert session.flow_id == "flow-1"

    session.apply_template_defaults()
    assert session.draft["item_type"] == "consumable"
    assert session.draft["stack_size"] == 20

    await session.transition(WizardStep.BASIC_INFO)
    assert session.step == WizardStep.BASIC_INFO

    loaded = await ItemWizardSession.load(store, 123, session.flow_id)
    assert loaded.step == WizardStep.BASIC_INFO
    assert loaded.draft["item_type"] == "consumable"
    assert loaded.template == "consumable"
    assert loaded.discord_guild_id == "456"


@pytest.mark.asyncio
async def test_session_forbids_invalid_transition() -> None:
    store = FakeSessionStore()
    session = await ItemWizardSession.create(
        store, flow_type="item_create", discord_user_id=1, discord_guild_id=None, channel_id=None
    )
    with pytest.raises(ValueError):
        await session.transition(WizardStep.REVIEW)


@pytest.mark.asyncio
async def test_session_delete_removes_draft() -> None:
    store = FakeSessionStore()
    session = await ItemWizardSession.create(
        store, flow_type="item_create", discord_user_id=1, discord_guild_id=None, channel_id=None
    )
    await session.delete()
    assert await store.get(1, session.flow_id) is None


# --- basic info modal (spec §9) ---------------------------------------------------


@pytest.mark.asyncio
async def test_basic_info_modal_derives_stable_id_from_display_name() -> None:
    captured: list[dict] = []

    async def on_submit(interaction, values):
        captured.append(values)

    modal = BasicInfoModal(on_submit, current={})
    modal.display_name._value = "Storm Rod"
    modal.item_id._value = ""
    modal.description._value = "A powerful rod"
    await modal.on_submit(FakeInteraction())

    assert captured == [
        {
            "title": "Storm Rod",
            "item_id": "storm_rod",
            "description": "A powerful rod",
        }
    ]


@pytest.mark.asyncio
async def test_basic_info_modal_keeps_manual_id_and_lowercases() -> None:
    captured: list[dict] = []

    async def on_submit(interaction, values):
        captured.append(values)

    modal = BasicInfoModal(on_submit, current={})
    modal.display_name._value = "Storm Rod"
    modal.item_id._value = "STORM-ROD"
    modal.description._value = ""
    await modal.on_submit(FakeInteraction())

    assert captured[0]["item_id"] == "storm-rod"
    assert captured[0]["description"] is None


@pytest.mark.asyncio
async def test_basic_info_modal_rejects_unslugifiable_name() -> None:
    failures: list[str] = []

    async def on_submit(interaction, values):
        raise AssertionError("must not proceed")

    modal = BasicInfoModal(on_submit, current={})
    modal.display_name._value = "!!!"
    modal.item_id._value = ""
    modal.description._value = ""
    await modal.on_submit(FakeInteraction(failures))

    assert failures and "stable item ID" in failures[0]


@pytest.mark.asyncio
async def test_basic_info_modal_rejects_invalid_manual_id() -> None:
    failures: list[str] = []

    async def on_submit(interaction, values):
        raise AssertionError("must not proceed")

    modal = BasicInfoModal(on_submit, current={})
    modal.display_name._value = "Storm Rod"
    modal.item_id._value = "Has Space"
    modal.description._value = ""
    await modal.on_submit(FakeInteraction(failures))

    assert failures and "Invalid Stable Item ID" in failures[0]


class FakeInteraction:
    def __init__(self, failures: list[str] | None = None):
        self._failures = failures if failures is not None else []
        self.modal = None

        class Response:
            def __init__(self, owner):
                self.owner = owner
                self.sent = []

            def is_done(self):
                return False

            async def send_message(self, *args, **kwargs):
                content = args[0] if args else kwargs.get("content")
                if content is not None:
                    self.owner._failures.append(content)
                self.sent.append((kwargs.get("embed"), kwargs.get("view")))

            async def send_modal(self, modal):
                self.owner.modal = modal

            async def edit_original_response(self, *args, **kwargs):
                return None

        self.response = Response(self)
        self.user = type("U", (), {"id": 1})()
        self.guild_id = 2
        self.channel_id = 3


# --- mechanics view (spec §11) ------------------------------------------------------


def _mechanics_view(template: str, draft: dict):
    async def noop(*args, **kwargs):
        return None

    return MechanicsView(
        initiator_id=1,
        template=template,
        draft=draft,
        on_persist=noop,
        on_continue=noop,
        on_back=noop,
        on_cancel=noop,
    )


def _component_labels(view) -> list[str]:
    labels = []
    for action_row in view.to_components():
        for comp in action_row.get("components", []):
            labels.append(comp.get("label") or comp.get("placeholder") or "")
    return labels


def test_mechanics_equipment_hides_stack_controls() -> None:
    view = _mechanics_view(
        "fishing_rod",
        {
            "item_type": "equipment",
            "equipment_slot": "rod",
            "stack_size": 1,
            "break_policy": "indestructible",
            "max_durability": None,
        },
    )
    labels = _component_labels(view)
    assert "Break behavior…" in labels
    assert "Set durability" in labels
    assert "Set stack size" not in labels


def test_mechanics_charm_keeps_slot_and_requires_selection() -> None:
    view = _mechanics_view(
        "charm",
        {
            "item_type": "equipment",
            "equipment_slot": None,
            "stack_size": 1,
            "break_policy": "indestructible",
            "max_durability": None,
        },
    )
    labels = _component_labels(view)
    assert "Charm slot…" in labels
    assert "Break behavior…" in labels
    assert view.continue_button.disabled is True

    view.draft["equipment_slot"] = "charm_1"
    view._update_state()
    assert view.continue_button.disabled is False


def test_mechanics_breakable_requires_durability() -> None:
    view = _mechanics_view(
        "fishing_rod",
        {
            "item_type": "equipment",
            "equipment_slot": "rod",
            "stack_size": 1,
            "break_policy": "unequip_broken",
            "max_durability": None,
        },
    )
    assert view.continue_button.disabled is True

    view.draft["max_durability"] = 150
    view._update_state()
    assert view.continue_button.disabled is False


def test_mechanics_non_equipment_hides_durability_and_slot() -> None:
    view = _mechanics_view(
        "consumable",
        {
            "item_type": "consumable",
            "equipment_slot": None,
            "stack_size": 20,
            "break_policy": "indestructible",
            "max_durability": None,
        },
    )
    labels = _component_labels(view)
    assert "Set stack size" in labels
    assert "Break behavior…" not in labels
    assert "Charm slot…" not in labels
    assert "Set durability" not in labels
    assert view.continue_button.disabled is False


# --- wizard entry point ------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_item_create_without_template_shows_template_picker() -> None:
    from app.interactions.items.wizard import start_item_create

    store = FakeSessionStore()
    interaction = FakeInteraction()
    await start_item_create(interaction, store, api=None)

    assert interaction.response.sent
    embed = interaction.response.sent[0][0]
    assert embed.title == "Create Item"
    view = interaction.response.sent[0][1]
    assert isinstance(view, TemplateSelectView)


@pytest.mark.asyncio
async def test_start_item_create_with_template_opens_basic_info_modal() -> None:
    from app.interactions.items.wizard import start_item_create

    store = FakeSessionStore()
    interaction = FakeInteraction()
    await start_item_create(interaction, store, api=None, template="consumable")

    modal = interaction.modal
    assert isinstance(modal, BasicInfoModal)
    # Defaults from the template must already be in the Redis draft.
    state = await store.get(interaction.user.id, "flow-1")
    assert state["draft"]["item_type"] == "consumable"
    assert state["draft"]["stack_size"] == 20


# --- review confirm uses the flow-based idempotency key (spec §48) -----------------


@pytest.mark.asyncio
async def test_review_confirm_uses_flow_based_idempotency_key() -> None:
    from app.interactions.items.wizard import _render_review

    store = FakeSessionStore()
    session = await ItemWizardSession.create(
        store,
        flow_type="item_create",
        discord_user_id=1,
        discord_guild_id=2,
        channel_id=3,
        template="material",
    )
    session.draft.update(
        {
            "title": "Iron Ore",
            "item_id": "iron_ore",
            "item_type": "material",
            "rarity": "common",
            "stack_size": 100,
            "break_policy": "indestructible",
            "max_durability": None,
            "effects": [],
        }
    )

    calls: list[tuple] = []

    class FakeApi:
        async def upsert_item(self, interaction, payload, *, idempotency_key=None):
            calls.append((payload["item_id"], idempotency_key))
            return {"ok": True}

    class EditInteraction:
        def __init__(self):
            self.view = None
            self.embed = None

            class Response:
                def is_done(self):
                    return False

            self.response = Response()
            self.user = type("U", (), {"id": 1})()
            self.guild_id = 2
            self.channel_id = 3

        async def edit_original_response(self, *, content=None, embed=None, view=None):
            self.view = view
            self.embed = embed

    interaction = EditInteraction()
    await _render_review(interaction, session, FakeApi())

    assert interaction.view is not None
    assert interaction.embed is not None

    class ConfirmClick:
        def __init__(self):
            class Response:
                def is_done(self):
                    return True

            self.response = Response()
            self.user = type("U", (), {"id": 1})()
            self.guild_id = 2
            self.channel_id = 3

        async def edit_original_response(self, **kwargs):
            return None

    await interaction.view.confirm.callback(ConfirmClick())

    assert calls == [("iron_ore", "discord:item-create:flow-1")]
    assert await store.get(1, session.flow_id) is None  # draft cleaned up


def test_rarity_defaults_continue_enabled_and_template_disabled() -> None:
    async def noop(*args, **kwargs):
        return None

    rarity = RarityView(1, noop, noop, noop, current="common")
    assert rarity.continue_button.disabled is False

    template = TemplateSelectView(1, noop, noop)
    assert template.continue_button.disabled is True
