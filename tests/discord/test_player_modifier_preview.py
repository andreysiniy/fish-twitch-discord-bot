from app.commands import register


def test_player_modifier_preview_shows_resolved_and_warning_for_override() -> None:
    embed = register._player_modifier_preview_embed(
        user_twitch_id="viewer_one",
        scope="fishing",
        stat_key="loot_luck_pct",
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
        stat_key="xp_gain_bonus_pct",
        op_label="Add",
        value="0.10",
        current_resolved="0.00",
        existing_source_count=0,
        source_key="promo",
        reason="Test",
    )
    fields = {field.name: field.value for field in embed.fields}
    assert "Warning" not in fields
