import discord

from app.interactions.confirms import ConfirmView
from app.interactions.launchers import ModalLauncherView
from app.interactions.sessions import WizardSessionStore
from app.presentation.pagination import PagedEmbedView
from app.commands import register


def test_json_embed_renders_cyrillic_without_ascii_escape() -> None:
    payload = {"title": "Удочка Левиафана", "description": "Мощная удочка"}
    embed = register._json_embed("Item", payload)
    assert "\\u" not in embed.description
    assert "Удочка Левиафана" in embed.description
    assert "Мощная удочка" in embed.description


def test_json_embed_truncation_is_marked() -> None:
    payload = {"data": "x" * 5000}
    embed = register._json_embed("Big", payload)
    assert "attached as a file" in embed.description


def test_timeouts_aligned_to_style_guide() -> None:
    # Audit §12: wizard session 600, view/modal 600, confirm 180, pagination 600.
    assert WizardSessionStore(None).ttl_seconds == 600
    launcher = ModalLauncherView(1, lambda: None)
    assert launcher.timeout == 600
    confirm = ConfirmView(1, lambda *_: None)
    assert confirm.timeout == 180
    pager = PagedEmbedView(1, "t", [], lambda x: ("a", "b"))
    assert pager.timeout == 600


def test_mutation_response_uses_valid_defer_for_component_interactions() -> None:
    """Confirm buttons ack with type 6, not the thinking defer Discord rejects."""
    import asyncio

    from app.commands.shared import _mutation_response

    class FakeResponse:
        def __init__(self):
            self.defer_kwargs = None
            self.edits = []

        async def defer(self, **kwargs):
            self.defer_kwargs = kwargs

        async def edit_original_response(self, **kwargs):
            self.edits.append(kwargs)

    class FakeInteraction:
        def __init__(self, type):
            self.type = type
            self.response = FakeResponse()

        async def edit_original_response(self, **kwargs):
            self.response.edits.append(kwargs)

    async def run():
        async def noop():
            return None

        # Component (button click): defer without thinking/ephemeral flags.
        component = FakeInteraction(discord.InteractionType.component)
        await _mutation_response(component, noop, "done")
        assert component.response.defer_kwargs == {}
        assert component.response.edits[0]["content"] == "done"

        # Slash command: keeps ephemeral thinking defer.
        slash = FakeInteraction(discord.InteractionType.application_command)
        await _mutation_response(slash, noop, "done")
        assert slash.response.defer_kwargs == {"ephemeral": True, "thinking": True}

        # Error path still edits the original response.
        errored = FakeInteraction(discord.InteractionType.component)

        async def boom():
            raise ValueError("nope")

        await _mutation_response(errored, boom, "done")
        assert "nope" in errored.response.edits[0]["content"]

    asyncio.run(run())
