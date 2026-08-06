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
