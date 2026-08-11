"""Tests for the item review screen (spec §36/§37/§38/§39/§65).

Covers the compatibility validation split into blocking errors vs warnings, the
type-aware review embed (irrelevant mechanics never shown), and the review view:
Confirm gating, edit-back buttons, and error re-rendering after a failed submit
(spec §61).
"""

import pytest

from app.api.errors import EngineError
from app.domain.item_review import compatibility_issues
from app.interactions.items.review import ItemReviewView, review_embed


def _equipment_draft(**overrides):
    draft = {
        "item_id": "storm_rod",
        "title": "Storm Rod",
        "item_type": "equipment",
        "equipment_slot": "rod",
        "rarity": "epic",
        "stack_size": 1,
        "break_policy": "indestructible",
        "max_durability": None,
        "effects": [],
        "schema_version": 1,
    }
    draft.update(overrides)
    return draft


def _material_draft(**overrides):
    draft = {
        "item_id": "iron_ore",
        "title": "Iron Ore",
        "item_type": "material",
        "equipment_slot": None,
        "rarity": "common",
        "stack_size": 100,
        "break_policy": "indestructible",
        "max_durability": None,
        "effects": [],
        "schema_version": 1,
    }
    draft.update(overrides)
    return draft


def _consumable_draft(**overrides):
    draft = _material_draft(item_type="consumable", stack_size=20)
    draft.update(overrides)
    return draft


def _lootbox_draft(**overrides):
    draft = _material_draft(item_type="lootbox", stack_size=20)
    draft.update(overrides)
    return draft


# --- compatibility validation (spec §36/§37) -------------------------------------


def test_equipment_with_no_effects_warns_not_blocks() -> None:
    errors, warnings = compatibility_issues(_equipment_draft())
    assert errors == []
    assert any("no effects" in warning for warning in warnings)


def test_consumable_with_no_effects_blocks() -> None:
    errors, warnings = compatibility_issues(_consumable_draft())
    assert any("at least one usable effect" in error for error in errors)


def test_consumable_with_effect_is_valid() -> None:
    errors, _ = compatibility_issues(
        _consumable_draft(effects=[{"type": "grant_mass", "mass": "5"}])
    )
    assert errors == []


def test_duplicate_effects_block_item_review() -> None:
    errors, _ = compatibility_issues(
        _equipment_draft(
            effects=[
                {
                    "type": "stat_add",
                    "stat": "fish_luck_change_ratio",
                    "value": "0.10",
                },
                {
                    "type": "stat_add",
                    "stat": "fish_luck_change_ratio",
                    "value": "0.20",
                },
            ]
        )
    )
    assert any("Duplicate effect is not allowed" in error for error in errors)


def test_lootbox_without_loot_producing_effect_blocks() -> None:
    errors, _ = compatibility_issues(_lootbox_draft())
    assert any("loot table roll or grant effect" in error for error in errors)


def test_lootbox_with_loot_table_roll_is_valid() -> None:
    errors, _ = compatibility_issues(
        _lootbox_draft(effects=[{"type": "loot_table_roll", "loot_table_id": "pool-1", "rolls": 1}])
    )
    assert errors == []


def test_non_equipment_with_slot_blocks() -> None:
    errors, _ = compatibility_issues(_material_draft(equipment_slot="rod"))
    assert any("does not support an equipment slot" in error for error in errors)


@pytest.mark.parametrize(
    "item_type",
    ["consumable", "lootbox", "material", "quest", "currency", "collectible"],
)
def test_non_equipment_with_durability_blocks(item_type) -> None:
    errors, _ = compatibility_issues(
        _material_draft(item_type=item_type, max_durability=150, break_policy="unequip_broken")
    )
    assert any("durability" in error.lower() for error in errors)


def test_non_equipment_with_break_behavior_blocks() -> None:
    errors, _ = compatibility_issues(_material_draft(break_policy="retain_broken"))
    assert any("break behavior" in error.lower() for error in errors)


def test_equipment_with_wrong_stack_blocks() -> None:
    errors, _ = compatibility_issues(_equipment_draft(stack_size=5))
    assert any("stack size 1" in error.lower() for error in errors)


def test_breakable_equipment_without_durability_blocks() -> None:
    errors, _ = compatibility_issues(_equipment_draft(break_policy="unequip_broken"))
    assert any("maximum durability" in error.lower() for error in errors)


def test_equipment_without_slot_blocks() -> None:
    errors, _ = compatibility_issues(_equipment_draft(equipment_slot=None))
    assert any("equipment slot" in error.lower() for error in errors)


def test_consume_durability_on_material_blocks() -> None:
    errors, _ = compatibility_issues(
        _material_draft(
            effects=[{"type": "consume_durability", "trigger": "after_cast", "amount": 1}]
        )
    )
    assert any("only compatible with equipment" in error for error in errors)


def test_consume_durability_on_indestructible_equipment_warns() -> None:
    _, warnings = compatibility_issues(
        _equipment_draft(
            effects=[{"type": "consume_durability", "trigger": "after_cast", "amount": 1}]
        )
    )
    assert any("indestructible" in warning for warning in warnings)


def test_consume_durability_on_breakable_equipment_is_valid() -> None:
    errors, _ = compatibility_issues(
        _equipment_draft(
            break_policy="unequip_broken",
            max_durability=150,
            effects=[{"type": "consume_durability", "trigger": "after_cast", "amount": 1}],
        )
    )
    assert errors == []


def test_consume_charge_on_material_blocks() -> None:
    errors, _ = compatibility_issues(
        _material_draft(effects=[{"type": "consume_charge", "trigger": "on_use", "amount": 1}])
    )
    assert any("only compatible with a consumable" in error for error in errors)


def test_consume_charge_on_equipment_blocks() -> None:
    errors, _ = compatibility_issues(
        _equipment_draft(
            break_policy="unequip_broken",
            max_durability=150,
            effects=[{"type": "consume_charge", "trigger": "on_use", "amount": 1}],
        )
    )
    assert any("only compatible with a consumable" in error for error in errors)


def test_consume_charge_on_consumable_without_max_charges_blocks() -> None:
    errors, _ = compatibility_issues(
        _consumable_draft(
            effects=[{"type": "consume_charge", "trigger": "on_use", "amount": 1}]
        )
    )
    assert any("maximum charge count" in error for error in errors)


def test_consume_charge_on_consumable_with_max_charges_is_valid() -> None:
    errors, _ = compatibility_issues(
        _consumable_draft(
            stack_size=1,
            max_charges=5,
            effects=[
                {"type": "consume_charge", "trigger": "on_use", "amount": 1},
                {"type": "grant_mass", "mass": "5"},
            ],
        )
    )
    assert errors == []


def test_non_consumable_with_max_charges_blocks() -> None:
    errors, _ = compatibility_issues(_material_draft(max_charges=5))
    assert any("Only consumables can carry a maximum charge count" in error for error in errors)


def test_consumable_max_charges_with_wrong_stack_blocks() -> None:
    errors, _ = compatibility_issues(_consumable_draft(stack_size=20, max_charges=5))
    assert any("stack size 1" in error.lower() for error in errors)


def test_passive_stat_on_non_equipment_blocks() -> None:
    errors, _ = compatibility_issues(
        _material_draft(
            effects=[{"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.10"}]
        )
    )
    assert any("only compatible with equipment" in error for error in errors)


def test_equipment_only_effect_on_consumable_blocks() -> None:
    errors, _ = compatibility_issues(
        _consumable_draft(
            effects=[
                {
                    "type": "mass_floor",
                    "protected_mass": "1000",
                    "scopes": ["robbery"],
                }
            ]
        )
    )
    assert any("only compatible with equipment" in error for error in errors)


def test_use_effect_on_equipment_blocks() -> None:
    errors, _ = compatibility_issues(
        _equipment_draft(
            effects=[{"type": "grant_mass", "mass": "5"}]
        )
    )
    assert any("only compatible with consumables and loot boxes" in error for error in errors)


def test_large_fishing_bonus_warns() -> None:
    _, warnings = compatibility_issues(
        _equipment_draft(
            effects=[{"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "1.50"}]
        )
    )
    assert any("very large fishing bonus" in warning for warning in warnings)


def test_moderate_fishing_bonus_does_not_warn() -> None:
    _, warnings = compatibility_issues(
        _equipment_draft(
            effects=[{"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.50"}]
        )
    )
    assert not any("very large fishing bonus" in warning for warning in warnings)


def test_lootbox_self_grant_warns() -> None:
    _, warnings = compatibility_issues(
        _lootbox_draft(
            item_id="treasure_box",
            effects=[
                {
                    "type": "grant_item",
                    "item_id": "treasure_box",
                    "quantity": 1,
                }
            ],
        )
    )
    assert any("grants this loot box again" in warning for warning in warnings)


def test_clean_equipment_with_effects_has_no_blocking_errors() -> None:
    errors, _ = compatibility_issues(
        _equipment_draft(
            break_policy="unequip_broken",
            max_durability=150,
            effects=[
                {"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.10"},
                {"type": "stat_add", "stat": "xp_gain_change_ratio", "value": "0.15"},
            ],
        )
    )
    assert errors == []


# --- type-aware review embed (spec §11.4/§38/§39) --------------------------------


def test_review_embed_equipment_shows_mechanics_and_hides_stack() -> None:
    embed = review_embed(
        _equipment_draft(
            break_policy="unequip_broken",
            max_durability=150,
            effects=[{"type": "stat_add", "stat": "fish_luck_change_ratio", "value": "0.10"}],
        ),
        template_label="Fishing Rod",
        schema_version=1,
    )
    assert embed.title == "Review Item"
    assert "Storm Rod" in embed.description
    assert "Epic Equipment" in embed.description
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Equipment Slot"] == "Fishing Rod"
    assert fields["Break Behavior"] == "Unequip When Broken"
    assert fields["Durability"] == "150"
    assert "Stack Size" not in fields
    assert "Fish Luck: +10%" in fields["Effects (1)"]
    assert "fish_luck_change_ratio" not in fields["Effects (1)"]


def test_review_embed_material_shows_stack_and_hides_equipment_mechanics() -> None:
    embed = review_embed(_material_draft(), schema_version=1)
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Stack Size"] == "100"
    assert "Equipment Slot" not in fields
    assert "Break Behavior" not in fields
    assert "Durability" not in fields


def test_review_embed_consumable_charge_shows_charge_mechanics() -> None:
    embed = review_embed(
        _consumable_draft(
            stack_size=1,
            max_charges=5,
            effects=[
                {"type": "consume_charge", "trigger": "on_use", "amount": 1},
                {"type": "grant_mass", "mass": "5"},
            ],
        ),
        schema_version=1,
    )
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Use Behavior"] == "Consume Charge"
    assert fields["Maximum Charges"] == "5"
    assert "Durability" not in fields
    assert "Consume Charge: 1 When the Item Is Used" in fields["Effects (2)"]


def test_review_embed_consumable_single_use_shows_stack_mechanics() -> None:
    embed = review_embed(
        _consumable_draft(
            stack_size=20,
            effects=[{"type": "grant_mass", "mass": "5"}],
        ),
        schema_version=1,
    )
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Use Behavior"] == "Consume One Item"
    assert fields["Stack Size"] == "20"
    assert "Maximum Charges" not in fields
    assert "Durability" not in fields


def test_review_embed_indestructible_durability_shown_as_not_used() -> None:
    embed = review_embed(_equipment_draft())
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Durability"] == "Not used"


def test_review_embed_shows_blocking_errors_and_no_false_warning_text() -> None:
    embed = review_embed(_consumable_draft())
    fields = {field.name: field.value for field in embed.fields}
    assert "Blocking errors" in fields
    assert "at least one usable effect" in fields["Blocking errors"]
    # With errors present the warnings field must not claim everything is fine.
    assert "No blocking validation errors found" not in "\n".join(fields.values())


def test_review_embed_shows_warnings() -> None:
    embed = review_embed(_equipment_draft())
    fields = {field.name: field.value for field in embed.fields}
    assert "Warnings" in fields
    assert "no effects" in fields["Warnings"]


def test_review_embed_clean_draft_shows_no_blocking_errors() -> None:
    embed = review_embed(_material_draft())
    fields = {field.name: field.value for field in embed.fields}
    assert "Blocking errors" not in fields
    assert "No blocking validation errors found" in fields["Warnings"]


def test_review_embed_extra_backend_error_is_rendered() -> None:
    embed = review_embed(_material_draft(), extra_errors=["An item with this ID already exists."])
    fields = {field.name: field.value for field in embed.fields}
    assert "already exists" in fields["Blocking errors"]


def test_review_embed_footer_has_schema_and_effect_count() -> None:
    embed = review_embed(
        _equipment_draft(effects=[{"type": "grant_mass", "mass": "5"}]),
        schema_version=2,
        version=4,
    )
    assert embed.footer.text == "version 4 · schema 2 · 1 effect(s)"


def test_review_embed_never_renders_raw_json() -> None:
    embed = review_embed(
        _equipment_draft(
            effects=[
                {"type": "stat_add", "stat": "positive_fish_reward_change_ratio", "value": "0.10"}
            ]
        )
    )
    rendered = "\n".join(field.value for field in embed.fields)
    assert "stat_add" not in rendered
    assert "0.10" not in rendered


# --- review view (spec §38/§40/§61) ---------------------------------------------


def _view(draft, **kwargs):
    async def noop(*args, **kwargs):
        return None

    return ItemReviewView(
        initiator_id=1,
        draft=draft,
        confirm_label=kwargs.pop("confirm_label", "Create Item"),
        on_confirm=kwargs.pop("on_confirm", noop),
        on_edit_basic=kwargs.pop("on_edit_basic", noop),
        on_edit_mechanics=kwargs.pop("on_edit_mechanics", noop),
        on_edit_effects=kwargs.pop("on_edit_effects", noop),
        on_cancel=kwargs.pop("on_cancel", noop),
        template_label=kwargs.pop("template_label", None),
        schema_version=kwargs.pop("schema_version", None),
        **kwargs,
    )


def _button_labels(view) -> list[str]:
    labels = []
    for action_row in view.to_components():
        for comp in action_row.get("components", []):
            labels.append(comp.get("label") or "")
    return labels


def test_review_view_has_confirm_edit_back_and_cancel_buttons() -> None:
    view = _view(_material_draft())
    labels = _button_labels(view)
    assert "Create Item" in labels
    assert "Edit Basic Info" in labels
    assert "Edit Mechanics" in labels
    assert "Edit Effects" in labels
    assert "Cancel" in labels


def test_review_view_confirm_disabled_when_blocking_errors() -> None:
    view = _view(_consumable_draft())
    assert view.confirm.disabled is True


def test_review_view_confirm_enabled_for_clean_draft() -> None:
    view = _view(_material_draft())
    assert view.confirm.disabled is False


def test_review_view_confirm_label_for_edit_flow() -> None:
    view = _view(_material_draft(), confirm_label="Save Changes")
    assert view.confirm.label == "Save Changes"


@pytest.mark.asyncio
async def test_review_view_reports_failed_submit_and_stays_interactive() -> None:
    async def boom(*args, **kwargs):
        raise EngineError(409, "DUPLICATE_ITEM", "An item with this ID already exists.")

    view = _view(_material_draft(), on_confirm=boom)

    class FakeResponse:
        def is_done(self):
            return True

    class FakeInteraction:
        def __init__(self):
            self.response = FakeResponse()
            self.edited = None

        async def edit_original_response(self, **kwargs):
            self.edited = kwargs

    interaction = FakeInteraction()
    await view.confirm.callback(interaction)

    assert interaction.edited is not None
    embed = interaction.edited["embed"]
    fields = {field.name: field.value for field in embed.fields}
    assert "already exists" in fields["Blocking errors"]
    # The view stays interactive so the admin can fix the draft and retry.
    assert view.confirm.disabled is False
    assert view.edit_basic.disabled is False


@pytest.mark.asyncio
async def test_review_view_edit_basic_routes_to_edit_callback() -> None:
    calls: list = []

    async def spy(*args, **kwargs):
        calls.append(args)

    view = _view(_material_draft(), on_edit_basic=spy)

    class FakeInteraction:
        user = type("U", (), {"id": 1})()

        class Response:
            async def send_modal(self, modal):
                return None

        response = Response()

    interaction = FakeInteraction()
    await view.edit_basic.callback(interaction)
    assert calls
    assert calls[0][0] is interaction
