from datetime import datetime, timezone
from types import SimpleNamespace

from services.streamelements.health_runner import (
    ProviderIdentityMismatch,
    StreamElementsHealthRunner,
    backoff_seconds,
    classify_probe_error,
)
from infrastructure.se_client import ProviderAuthenticationError, ProviderRateLimitError


def test_health_error_classification_separates_invalid_and_degraded() -> None:
    assert classify_probe_error(ProviderAuthenticationError("no", status_code=401)) == (
        "invalid",
        "STREAM_ELEMENTS_INVALID_CREDENTIALS",
    )
    assert classify_probe_error(ProviderRateLimitError("busy", status_code=429)) == (
        "degraded",
        "STREAM_ELEMENTS_RATE_LIMITED",
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
