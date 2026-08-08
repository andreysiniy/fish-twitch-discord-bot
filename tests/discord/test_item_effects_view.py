"""Tests for the category-driven item effects editor (spec §12/§21/§34/§35)."""


from app.domain.item_effect_registry import TRIGGERED_EFFECT_FORMS
from app.interactions.items.effect_forms import StatValueModal
from app.interactions.items.effects import (
    AdvancedEffectPickerView,
    EffectCategoryPickerView,
    EffectFormView,
    ItemEffectsView,
)


class FakeApi:
    async def items(self, interaction):
        return {"items": [{"item_id": "storm_rod", "title": "Storm Rod"}]}

    async def loot_tables(self, interaction):
        return {"items": [{"table_id": "pool-1", "title": "River Loot"}]}


def _editor(effects):
    return ItemEffectsView(
        initiator_id=1,
        effects=effects,
        on_done=lambda *_: None,
        api=FakeApi(),
    )


# --- presentation ---------------------------------------------------------------


def test_item_effects_view_lists_human_descriptions() -> None:
    view = _editor(
        [
            {"type": "stat_add", "stat": "positive_fish_reward_change_ratio", "value": "0.10"},
            {"type": "grant_mass", "mass": "5"},
        ]
    )
    embed = view._embed()
    fields = {field.name: field.value for field in embed.fields}
    assert "Positive Fish Reward: +10%" in fields["Effects"]
    assert "Grant Mass: 5 kg" in fields["Effects"]
    assert "positive_fish_reward_change_ratio" not in fields["Effects"]


def test_item_effects_view_empty_draft_serializes_a_valid_select() -> None:
    """An empty draft must still serialize a select with at least one option
    (mirrors the effects_editor regression for a fresh item)."""
    view = _editor([])
    selects = []
    for component in view.to_components():
        for inner in component.get("components", []):
            if inner["type"] == 3:
                selects.append(inner)
    assert selects, "expected at least one select"
    pick = next(
        (s for s in selects if "Add an effect first" in s.get("placeholder", "")),
        selects[0],
    )
    assert pick.get("options")
    assert pick.get("disabled") is True

    view.effects.append({"type": "grant_mass", "mass": "5"})
    view._rebuild_pick_options()
    assert view.pick_effect.disabled is False
    assert len(view.pick_effect.options) == 1


def test_item_effects_view_limits_standard_effect_count() -> None:
    effects = [{"type": "grant_mass", "mass": str(i)} for i in range(10)]
    view = _editor(effects)
    assert view.add_button.disabled is True
    embed = view._embed()
    assert any("maximum number of effects" in field.value for field in embed.fields)


def test_item_effects_view_has_continue_back_cancel() -> None:
    view = _editor([])
    assert view.continue_button.disabled is False
    assert view.back_button.disabled is False
    assert view.cancel_button.disabled is False


def test_effect_category_picker_starts_with_category_placeholder() -> None:
    view = EffectCategoryPickerView(_editor([]))
    assert view.effect_select.disabled is True
    assert view.effect_select.options[0].value == "-1"


def test_advanced_effect_picker_needs_operation_first() -> None:
    view = AdvancedEffectPickerView(_editor([]), "points_flat_bonus")
    assert view.continue_button.disabled is True
    view._operation = "add"
    view.continue_button.disabled = False
    assert view.continue_button.disabled is False


# --- triggered form selects (spec §22-§26) --------------------------------------


def test_effect_form_view_disables_continue_until_required_selects_chosen() -> None:
    form = TRIGGERED_EFFECT_FORMS["block_action"]
    view = EffectFormView(_editor([]), form)
    assert view.continue_button.disabled is True
    view.select_values["trigger"] = "after_reward_roll"
    view._update_state()
    assert view.continue_button.disabled is True
    view.select_values["target_action_types"] = ["nothing"]
    view._update_state()
    assert view.continue_button.disabled is False


def test_effect_form_view_prefills_select_values_when_editing() -> None:
    """Spec §34: editing an effect keeps its stored select values, so Continue
    is enabled and the payload is not silently reset."""
    form = TRIGGERED_EFFECT_FORMS["block_action"]
    current = {
        "type": "block_action",
        "trigger": "after_reward_roll",
        "target_action_types": ["nothing"],
        "chance": "0.5",
        "durability_cost": 2,
    }
    view = EffectFormView(_editor([]), form, current=current)
    assert view.select_values == {
        "trigger": "after_reward_roll",
        "target_action_types": ["nothing"],
    }
    assert view.continue_button.disabled is False
    assert view._placeholder_for(view.form.fields[0]) == "Trigger: After Reward Roll"


def test_effect_form_view_keeps_stale_entity_reference_visible() -> None:
    """If the referenced item no longer exists, editing must still show the
    stored reference as a choice instead of silently dropping it."""
    form = TRIGGERED_EFFECT_FORMS["grant_item"]
    current = {"type": "grant_item", "item_id": "retired_item", "quantity": 1}
    view = EffectFormView(_editor([]), form, current=current, entity_options={})
    widget = view.select_widgets["item_id"]
    values = {option.value for option in widget.options}
    assert "retired_item" in values


def test_effect_form_view_entity_form_without_choices_disables_select() -> None:
    form = TRIGGERED_EFFECT_FORMS["grant_item"]
    view = EffectFormView(_editor([]), form, entity_options={})
    assert view.select_widgets["item_id"].disabled is True
    assert view.continue_button.disabled is True


def test_stat_value_modal_prefills_current_percent() -> None:
    modal = StatValueModal(
        "fish_luck_change_ratio",
        lambda payload: None,
        current="0.25",
    )
    assert modal.value.default == "25"
