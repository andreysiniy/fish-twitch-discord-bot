from app.commands import register


def test_player_modifier_preview_shows_resolved_and_warning_for_override() -> None:
    embed = register._player_modifier_preview_embed(
        user_twitch_id="viewer_one",
        scope="fishing",
        stat_key="fish_luck_change_ratio",
        op_label="Override",
        value="0.50",
        current_resolved="0.05",
        existing_source_count=2,
        source_key="promo.weekly",
        reason="Weekly winner",
    )
    fields = {field.name: field.value for field in embed.fields}
    assert "0.05" in fields["Current resolved value"]
    assert fields["Existing sources"] == "2"
    assert "promo.weekly" in fields["Source"]
    assert "⚠️ Warning" in fields or "Warning" in fields


def test_player_modifier_preview_neutral_has_no_warning() -> None:
    embed = register._player_modifier_preview_embed(
        user_twitch_id="viewer_one",
        scope="fishing",
        stat_key="xp_gain_change_ratio",
        op_label="Add",
        value="0.10",
        current_resolved="0.00",
        existing_source_count=0,
        source_key="promo",
        reason="Test",
    )
    fields = {field.name: field.value for field in embed.fields}
    assert "Warning" not in fields


def test_resolve_viewer_prefers_argument_and_falls_back_to_own_account() -> None:
    """viewer param wins; omitted viewer uses the admin's linked Twitch login."""
    import asyncio

    from app.commands.players import _resolve_viewer
    from app.api.errors import EngineError

    class FakeApi:
        def __init__(self, login):
            self.login = login

        async def status(self, interaction):
            return {"twitch": {"id": "9001", "login": self.login}}

    class FakeInteraction:
        pass

    async def run():
        resolved = await _resolve_viewer(FakeApi("mylogin"), FakeInteraction(), "CoolViewer")
        assert resolved == "CoolViewer"
        resolved = await _resolve_viewer(FakeApi("mylogin"), FakeInteraction(), None)
        assert resolved == "mylogin"
        try:
            await _resolve_viewer(FakeApi(None), FakeInteraction(), None)
            raise AssertionError("expected LINK_REQUIRED")
        except EngineError as error:
            assert error.code == "LINK_REQUIRED"

    asyncio.run(run())


def test_player_modifier_value_is_converted_to_ratio_for_percent_ops() -> None:
    """10 means +10% for add/override/min/max, but a raw multiplier for multiply."""
    from datetime import datetime, timedelta, timezone

    from app.commands.players import _player_modifier_payload

    payload = _player_modifier_payload(
        stat_key="fish_luck_change_ratio",
        operation="add",
        scope="fishing",
        value="10",
        source_key="promo",
        reason="test",
        expected_version=None,
        expires_in=None,
    )
    assert payload["value"] == "0.1"

    payload = _player_modifier_payload(
        stat_key="fish_luck_change_ratio",
        operation="multiply",
        scope="fishing",
        value="2",
        source_key="promo",
        reason="test",
        expected_version=None,
        expires_in=None,
    )
    assert payload["value"] == "2"

    payload = _player_modifier_payload(
        stat_key="fish_luck_change_ratio",
        operation="add",
        scope="fishing",
        value="-50",
        source_key="promo",
        reason="test",
        expected_version=None,
        expires_in="2h",
    )
    assert payload["value"] == "-0.5"
    expires_at = datetime.fromisoformat(payload["expires_at"].replace("+00:00", "+00:00"))
    assert expires_at.tzinfo is not None
    remaining = expires_at - datetime.now(timezone.utc)
    assert timedelta(hours=1) < remaining < timedelta(hours=3)
