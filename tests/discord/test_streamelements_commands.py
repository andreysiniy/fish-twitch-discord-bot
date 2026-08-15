"""Tests for the readable StreamElements economy operation cards."""

import discord
from app.commands.streamelements import economy_operation_detail_embed
from app.presentation.pagination import PagedEmbedView


def _operation(**overrides) -> dict:
    item = {
        "operation_id": "0198f72f-4bc5-7e90-9081-e7bf4df21d56",
        "operation_type": "buy",
        "state": "completed",
        "username": "viewer_one",
        "mass_delta": "-11.00",
        "mass_effective": "11.00",
        "points_delta": "-1320",
        "points_calculated": "1320",
        "rate": "120.0000",
        "provider_channel_id": "provider-channel",
        "provider_points_cap": 2_147_483_647,
        "provider_balance_before": 10501,
        "provider_balance_after": 9181,
        "provider_points_headroom_before": 2_147_473_146,
        "provider_points_headroom_after": 2_147_474_466,
        "external_applied": True,
        "attempts": 1,
        "requested_at": "2026-08-15T21:25:24+00:00",
        "completed_at": "2026-08-15T21:25:25+00:00",
        "player_mass_before": "100.00",
        "player_mass_after": "89.00",
    }
    item.update(overrides)
    return item


def test_economy_operation_embed_is_a_readable_detail_card() -> None:
    embed = economy_operation_detail_embed(_operation())
    fields = {field.name: field.value for field in embed.fields}

    assert embed.title == "Economy operation 0198f72f"
    assert embed.color == discord.Color.green()
    assert fields["Status"] == "Completed"
    assert fields["Type"] == "Buy"
    assert fields["Time"] == "<t:1786829124:f>"
    assert fields["Mass"] == "100 kg → 89 kg\nChange: -11 kg\nEffective: 11 kg"
    assert "Change: -1320 points" in fields["Points"]
    assert "Balance: 10501 → 9181 points" in fields["Points"]
    assert "Rate: 120 points/kg" in fields["Processing"]
    assert "Provider mutation: applied" in fields["Processing"]


def test_economy_operation_embed_shows_actionable_failure_without_raw_payload() -> None:
    embed = economy_operation_detail_embed(
        _operation(
            state="reconciliation_required",
            error_code="PROVIDER_TIMEOUT",
            last_error="The provider did not respond before the request deadline.",
            external_applied=False,
        )
    )
    fields = {field.name: field.value for field in embed.fields}

    assert embed.color == discord.Color.orange()
    assert fields["Status"] == "Reconciliation Required"
    assert fields["Issue"] == (
        "Provider Timeout: The provider did not respond before the request deadline."
    )


def test_economy_operations_use_one_detail_card_per_page() -> None:
    view = PagedEmbedView(
        111,
        "Recent economy operations",
        [_operation(), _operation(operation_id="another-operation")],
        embed_builder=economy_operation_detail_embed,
    )

    assert view.page_size == 1
    assert view.page_count == 2
    assert "Economy operation 0198f72f" == view.embed().title
    view.page = 1
    assert "Economy operation another-" == view.embed().title
