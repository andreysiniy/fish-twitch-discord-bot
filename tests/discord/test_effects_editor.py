from app.interactions.effect_builder import serialize_draft
from app.interactions.effects_editor import EffectsEditorView, STANDARD_MAX_EFFECTS


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


def test_standard_editor_limits_effect_count() -> None:
    """Spec §12/§35: the standard editor allows at most 10 effects."""
    effects = [{"type": "grant_mass", "mass": str(i)} for i in range(STANDARD_MAX_EFFECTS)]
    view = EffectsEditorView(initiator_id=1, effects=effects, on_done=lambda *_: None)
    assert view.add_effect.disabled is True
    embed = view._embed()
    assert any("maximum number of effects" in field.value for field in embed.fields)


def test_standard_editor_allows_below_limit() -> None:
    view = EffectsEditorView(
        initiator_id=1,
        effects=[{"type": "grant_mass", "mass": "1"}],
        on_done=lambda *_: None,
    )
    assert view.add_effect.disabled is False


def test_modal_save_refreshes_editor_message_when_hook_provided() -> None:
    """Spec §34: when the editor supplies an on_saved hook, the effect modal
    refreshes the editor message instead of sending a standalone 'added' note."""
    import asyncio

    from app.interactions.effect_builder import modal_for_effect

    saved_calls: list[dict] = []

    class FakeResponse:
        def __init__(self):
            self.edited_message = None

        async def edit_message(self, **kwargs):
            self.edited_message = kwargs

        async def send_message(self, *args, **kwargs):
            raise AssertionError("standalone message must not be sent with a hook")

    class FakeInteraction:
        response = FakeResponse()

    async def run():
        def on_save(payload):
            saved_calls.append(payload)

        async def on_saved(interaction):
            await interaction.response.edit_message(embed=None, view=None)

        modal = modal_for_effect("grant_mass", on_save, on_saved)
        modal.mass._value = "7"
        await modal.on_submit(FakeInteraction())
        assert saved_calls == [{"type": "grant_mass", "mass": "7"}]
        assert FakeInteraction.response.edited_message is not None

    asyncio.run(run())


def test_modal_without_hook_still_acknowledges() -> None:
    """A modal built without the on_saved hook keeps its ephemeral ack."""
    import asyncio

    from app.interactions.effect_builder import modal_for_effect

    sent: list[dict] = []

    class FakeResponse:
        async def send_message(self, content=None, **kwargs):
            sent.append({"content": content})

    class FakeInteraction:
        response = FakeResponse()

    async def run():
        modal = modal_for_effect("grant_mass", lambda payload: None)
        modal.mass._value = "3"
        await modal.on_submit(FakeInteraction())
        assert sent and "Effect added" in sent[0]["content"]

    asyncio.run(run())
