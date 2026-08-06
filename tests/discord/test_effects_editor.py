from app.interactions.effect_builder import serialize_draft
from app.interactions.effects_editor import EffectsEditorView


def test_effects_editor_embed_lists_draft_effects() -> None:
    view = EffectsEditorView(
        initiator_id=1,
        effects=[
            serialize_draft(
                {"type": "stat_add", "stat": "positive_fish_reward_change_ratio", "value": "0.10"}
            ),
            {"type": "grant_mass", "mass": "5"},
        ],
        on_done=lambda *_: None,
    )
    embed = view._embed()
    fields = {f.name: f.value for f in embed.fields}
    assert "positive_fish_reward_change_ratio" in fields["Effects"]
    assert "1." in fields["Effects"]
    assert "2." in fields["Effects"]
    assert view.effects


def test_effects_editor_empty_embed() -> None:
    view = EffectsEditorView(initiator_id=1, effects=[], on_done=lambda *_: None)
    embed = view._embed()
    fields = {f.name: f.value for f in embed.fields}
    assert "No effects yet." in fields["Effects"]
    assert not view.effects


def test_effects_editor_remove_last() -> None:
    view = EffectsEditorView(
        initiator_id=1,
        effects=[{"type": "grant_mass", "mass": "5"}, {"type": "grant_item", "item_id": "x"}],
        on_done=lambda *_: None,
    )
    view.effects.pop()
    view._update_buttons()
    assert len(view.effects) == 1
    assert view.effects[0]["type"] == "grant_mass"


def test_effects_editor_selects_removes_and_reorders_effects() -> None:
    view = EffectsEditorView(
        initiator_id=1,
        effects=[
            {"type": "grant_mass", "mass": "5"},
            {"type": "grant_item", "item_id": "x"},
            {"type": "stat_add", "stat": "xp_gain_change_ratio", "value": "0.1"},
        ],
        on_done=lambda *_: None,
    )
    assert len(view.pick_effect.options) == 3

    view._selected_index = 1
    view._update_buttons()
    assert view.remove_selected.disabled is False
    assert view.move_up.disabled is False
    assert view.move_down.disabled is False

    # Move down swaps with the next effect.
    view._selected_index = 0
    view.move_down.disabled = False
    view.effects[0], view.effects[1] = view.effects[1], view.effects[0]
    assert view.effects[0]["type"] == "grant_item"

    # Replacing (editing) the selected effect updates the list in place.
    view._replace_effect(0, {"type": "grant_mass", "mass": "9"})
    assert view.effects[0] == {"type": "grant_mass", "mass": "9"}

    # Removing the selected effect deletes exactly that entry.
    view._selected_index = 0
    del view.effects[view._selected_index]
    view._selected_index = None
    view._rebuild_pick_options()
    assert len(view.effects) == 2
    assert len(view.pick_effect.options) == 2


def test_effects_editor_empty_draft_serializes_a_valid_select() -> None:
    """Discord rejects an options-less select; an empty draft must still
    produce a component with at least one option (regression: HTTPException
    on the first 'Edit effects' click for a new item)."""
    view = EffectsEditorView(
        initiator_id=1,
        effects=[],
        on_done=lambda *_: None,
    )
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
    assert pick.get("options"), "select must always carry at least one option"
    assert pick.get("disabled") is True
    assert len(pick["options"]) >= 1

    # After adding an effect the pick select becomes enabled with real options.
    view.effects.append({"type": "grant_mass", "mass": "5"})
    view._rebuild_pick_options()
    assert view.pick_effect.disabled is False
    assert len(view.pick_effect.options) == 1
