"""Tests for the Discord-facing StreamElements operation payload."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from services.streamelements_integration_service import StreamElementsIntegrationService


def test_operation_serialization_includes_mass_snapshots_and_lifecycle_data() -> None:
    requested_at = datetime(2026, 8, 15, 21, 25, 24, tzinfo=timezone.utc)
    started_at = datetime(2026, 8, 15, 21, 25, 25, tzinfo=timezone.utc)
    completed_at = datetime(2026, 8, 15, 21, 25, 26, tzinfo=timezone.utc)
    row = SimpleNamespace(
        id=uuid4(),
        operation_type="buy",
        state="completed",
        twitch_username="viewer_one",
        mass_delta=Decimal("-11.00"),
        mass_effective=Decimal("11.00"),
        pricing_mode_snapshot="buy_rate",
        points_delta=Decimal(-1320),
        points_calculated=Decimal(1320),
        rate_used_snapshot=Decimal("120.0000"),
        player_mass_before=Decimal("100.00"),
        player_mass_after=Decimal("89.00"),
        provider_channel_id_snapshot="provider-channel",
        provider_points_cap=2_147_483_647,
        provider_balance_before=10501,
        provider_balance_after=9181,
        provider_points_headroom_before=2_147_473_146,
        provider_points_headroom_after=2_147_474_466,
        external_applied=True,
        attempts=1,
        last_error=None,
        error_code=None,
        reconciliation_reason=None,
        requested_at=requested_at,
        started_at=started_at,
        completed_at=completed_at,
    )

    result = StreamElementsIntegrationService._serialize_operation(None, row)

    assert result["mass_effective"] == "11.00"
    assert result["pricing_mode"] == "buy_rate"
    assert result["player_mass_before"] == "100.00"
    assert result["player_mass_after"] == "89.00"
    assert result["started_at"] == started_at.isoformat()
    assert result["completed_at"] == completed_at.isoformat()
