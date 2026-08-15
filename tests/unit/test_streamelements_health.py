from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.streamelements.health_runner import (
    ProviderIdentityMismatch,
    StreamElementsHealthRunner,
    backoff_seconds,
    classify_probe_error,
    regular_interval_seconds,
)
from infrastructure.se_client import (
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderServerReadError,
)
from services.streamelements_integration_service import StreamElementsIntegrationService


def test_health_error_classification_separates_invalid_and_degraded() -> None:
    assert classify_probe_error(ProviderAuthenticationError("no", status_code=401)) == (
        "invalid",
        "STREAM_ELEMENTS_INVALID_CREDENTIALS",
    )
    assert classify_probe_error(ProviderRateLimitError("busy", status_code=429)) == (
        "degraded",
        "STREAM_ELEMENTS_RATE_LIMITED",
    )
    assert classify_probe_error(ProviderServerReadError("timeout", status_code=503)) == (
        "degraded",
        "STREAM_ELEMENTS_UNAVAILABLE",
    )
    assert classify_probe_error(ProviderIdentityMismatch("wrong")) == (
        "invalid",
        "STREAM_ELEMENTS_PROVIDER_IDENTITY_MISMATCH",
    )


def test_health_backoff_matches_spec_table() -> None:
    assert backoff_seconds(1, rng=lambda _low, _high: 1.0) == 60
    assert backoff_seconds(2, rng=lambda _low, _high: 1.0) == 120
    assert backoff_seconds(3, rng=lambda _low, _high: 1.0) == 300
    assert backoff_seconds(4, rng=lambda _low, _high: 1.0) == 900
    assert backoff_seconds(5, rng=lambda _low, _high: 1.0) == 1800


def test_health_jitter_stays_within_the_configured_ten_percent_window() -> None:
    assert backoff_seconds(1, rng=lambda _low, _high: 0.9) == 54
    assert backoff_seconds(1, rng=lambda _low, _high: 1.1) == 66
    assert regular_interval_seconds(rng=lambda _low, _high: 0.9) == 1620
    assert regular_interval_seconds(rng=lambda _low, _high: 1.1) == pytest.approx(1980)


def test_manual_provider_failure_uses_the_same_retry_policy() -> None:
    integration = SimpleNamespace(
        status="connected",
        last_check_at=None,
        last_error_at=None,
        last_error_code=None,
        consecutive_failures=0,
        next_validation_at=None,
    )
    StreamElementsIntegrationService._record_failure(
        integration,
        ProviderRateLimitError("busy", status_code=429),
    )
    assert integration.status == "degraded"
    assert integration.consecutive_failures == 1
    assert integration.next_validation_at is not None
    delay = (integration.next_validation_at - integration.last_check_at).total_seconds()
    assert 54 <= delay <= 66


def test_successful_health_update_resets_failures() -> None:
    runner = StreamElementsHealthRunner.__new__(StreamElementsHealthRunner)
    runner.random_fn = lambda _low, _high: 1.0
    integration = SimpleNamespace(
        status="degraded",
        last_check_at=None,
        last_success_at=None,
        last_validated_at=None,
        last_error_at=datetime.now(timezone.utc),
        last_error_code="STREAM_ELEMENTS_RATE_LIMITED",
        consecutive_failures=3,
        validation_latency_ms=None,
        next_validation_at=None,
    )
    runner._apply_success(integration, SimpleNamespace(latency_ms=12))
    assert integration.status == "connected"
    assert integration.consecutive_failures == 0
    assert integration.last_error_code is None
    assert integration.next_validation_at is not None
