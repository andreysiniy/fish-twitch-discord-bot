"""Unit tests for the Discord fishing cast history commands."""

import discord
from app.commands.casts import (
    cast_detail_embed,
    cast_stats_embed,
    register_casts_group,
)


def test_paged_embed_view_renders_one_detail_embed_per_page() -> None:
    from app.presentation.pagination import PagedEmbedView

    items = [
        {"cast_id": "a", "reward": {"reward_type": "fish"}},
        {"cast_id": "b", "reward": {"reward_type": "dupe"}},
    ]
    view = PagedEmbedView(111, "Casts", items, embed_builder=cast_detail_embed)
    assert view.page_size == 1
    assert view.page_count == 2
    assert "a" in view.embed().title
    assert "Page 1/2" in view.embed().footer.text
    view.page = 1
    assert "b" in view.embed().title


def test_paged_embed_view_empty_items() -> None:
    from app.presentation.pagination import PagedEmbedView

    view = PagedEmbedView(111, "Casts", [], embed_builder=cast_detail_embed)
    assert view.page_count == 1
    assert "No entries" in view.embed().description


def test_cast_detail_embed_status_color() -> None:
    embed = cast_detail_embed(
        {
            "cast_id": "0198f72f-4bc5-7e90-9081-e7bf4df21d56",
            "status": "resolved",
            "username": "viewer_one",
            "location_id": "abyss",
            "state": {
                "mass_before": "100.00",
                "mass_after": "129.40",
                "mass_delta_applied": "29.40",
                "xp_before": 100,
                "xp_after": 120,
                "xp_gained": 20,
                "level_before": 4,
                "level_after": 4,
            },
            "reward": {"reward_type": "fish", "reward_id": "reward-fish-20pct"},
            "items": [],
        }
    )
    assert embed.color == discord.Color.green()
    fields = {f.name: f.value for f in embed.fields}
    assert "Viewer" in fields
    assert "100.00 → 129.40" in fields["Mass"]


def test_cast_stats_embed_computes_drop_rate() -> None:
    embed = cast_stats_embed(
        {
            "casts": 4820,
            "unique_players": 183,
            "failures": 3,
            "mass_positive": 1240500,
            "mass_negative": 312400,
            "total_xp": 28920,
            "items_actual": 282,
            "items_expected": 289.4,
        }
    )
    fields = {f.name: f.value for f in embed.fields}
    assert "282 actual / 289.4 expected" in fields["Items"]
    assert fields["Casts"] == "4820"


def test_register_casts_group_creates_subcommands() -> None:
    class FakeTree:
        pass

    tree = FakeTree()
    api = object()
    parent = discord.app_commands.Group(name="fish", description="Manage Fisher Bot")
    group = register_casts_group(tree, api, parent)  # type: ignore[arg-type]
    assert group.name == "cast"
    names = {cmd.name for cmd in group.commands}
    assert {"recent", "show", "search", "stats", "export"} <= names


class _FakeResponse:
    async def defer(self, ephemeral=False):
        self.deferred = True


class _FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, ephemeral=False, file=None, embed=None, embeds=None, view=None):
        self.sent.append(content)


class _FakeInteraction:
    def __init__(self):
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()
        self.user = type("U", (), {"id": 111, "display_name": "Owner"})()
        self.guild = type("G", (), {"name": "Test Guild"})()
        self.id = 999


class _FakeApi:
    """Records kwargs for cast history calls instead of hitting the backend."""

    def __init__(self):
        self.recent_kwargs = None
        self.search_kwargs = None

    async def channel_id(self, interaction):
        return "464887139"

    async def recent_casts(self, interaction, **kwargs):
        self.recent_kwargs = kwargs
        return {"items": []}

    async def search_casts(self, interaction, **kwargs):
        self.search_kwargs = kwargs
        return {"items": []}


def _run_callback(group_name: str, api: _FakeApi, **params) -> _FakeInteraction:
    """Invoke a cast subcommand callback with a fake interaction.

    Raises if the callback degraded to the generic error message, so wrapper
    bugs (e.g. missing client kwargs, removed discord.utils helpers) surface
    in tests instead of being swallowed by the command's except handler.
    """
    import asyncio
    from app.commands.casts import register_casts_group

    tree = discord.app_commands.CommandTree(discord.Client(intents=discord.Intents.default()))
    parent = discord.app_commands.Group(name="fish", description="fish")
    group = register_casts_group(tree, api, parent)
    command = next(c for c in group.commands if c.name == group_name)
    interaction = _FakeInteraction()
    asyncio.run(command.callback(interaction, **params))
    assert not any(
        "Something went wrong" in (s or "") for s in interaction.followup.sent
    ), f"{group_name} fell back to the generic error: {interaction.followup.sent}"
    return interaction


def test_cast_export_passes_viewer_as_username_filter() -> None:
    api = _FakeApi()
    interaction = _run_callback("export", api, viewer="srakjopa")
    assert api.recent_kwargs == {
        "limit": 25,
        "username": "srakjopa",
        "status": None,
    }
    assert interaction.followup.sent[0].startswith("Exported 0 fishing cast")


def test_cast_recent_and_search_accept_username_kwargs() -> None:
    api = _FakeApi()
    _run_callback("recent", api, viewer="viewer_one", limit=10)
    assert api.recent_kwargs["username"] == "viewer_one"

    api2 = _FakeApi()
    _run_callback("search", api2, viewer="viewer_one", username="other")
    assert api2.search_kwargs["username"] == "viewer_one"


def test_cast_detail_embed_rounds_reward_fields() -> None:
    embed = cast_detail_embed(
        {
            "cast_id": "0198f72f-4bc5-7e90-9081-e7bf4df21d56",
            "status": "resolved",
            "username": "viewer_one",
            "location_id": "abyss",
            "state": {
                "mass_before": "100.00",
                "mass_after": "129.40",
                "mass_delta_applied": "29.40",
                "xp_before": 100,
                "xp_after": 120,
                "xp_gained": 20,
                "level_before": 4,
                "level_after": 4,
            },
            "reward": {
                "reward_type": "fish",
                "reward_id": "rew-1",
                "weight": "1835.00000000",
                "total_weight": "95951.00000000",
                "probability": "0.019124344718",
                "roll": "1597.907049000000",
            },
            "items": [],
        }
    )
    fields = {f.name: f.value for f in embed.fields}
    assert "probability: 1.91% • roll: 1,597.91" in fields["Reward"]
    assert "weight: 1835 / 95951" in fields["Reward"]


def test_cast_detail_embed_handles_missing_reward_trace() -> None:
    embed = cast_detail_embed(
        {
            "cast_id": "0198f72f-4bc5-7e90-9081-e7bf4df21d56",
            "status": "resolved",
            "username": "viewer_one",
            "location_id": "abyss",
            "state": {
                "mass_before": "100.00",
                "mass_after": "129.40",
                "mass_delta_applied": "29.40",
                "xp_before": 100,
                "xp_after": 120,
                "xp_gained": 20,
                "level_before": 4,
                "level_after": 4,
            },
            "reward": {"reward_type": "fish", "reward_id": "rew-1"},
            "items": [],
        }
    )
    fields = {f.name: f.value for f in embed.fields}
    assert "probability: n/a • roll: n/a" in fields["Reward"]
    assert "weight:" not in fields["Reward"]
