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
