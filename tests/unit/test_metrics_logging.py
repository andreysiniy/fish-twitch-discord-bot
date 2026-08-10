import logging

from core import metrics


def test_log_summary_logs_snapshot_without_raising(caplog) -> None:
    metrics.reset()
    metrics.inc("fishing_casts_total", {"status": "resolved"})
    with caplog.at_level(logging.INFO):
        metrics.log_summary(logging.getLogger("test_metrics"))
    assert "fishing_metrics_snapshot" in caplog.text
    assert "fishing_casts_total" in caplog.text


def test_log_summary_noop_when_empty(caplog) -> None:
    metrics.reset()
    with caplog.at_level(logging.INFO):
        metrics.log_summary(logging.getLogger("test_metrics"))
    assert "fishing_metrics_snapshot" not in caplog.text


def test_prometheus_text_exposes_counter_and_gauge() -> None:
    metrics.reset()
    metrics.inc("fishing_casts_total", {"status": "resolved"})
    metrics.set_gauge("fishing_wizard_sessions_active", 2)

    payload = metrics.prometheus_text()

    assert "# TYPE fishing_casts_total counter" in payload
    assert 'fishing_casts_total{status="resolved"} 1' in payload
    assert "# TYPE fishing_wizard_sessions_active gauge" in payload
    assert "fishing_wizard_sessions_active 2" in payload
