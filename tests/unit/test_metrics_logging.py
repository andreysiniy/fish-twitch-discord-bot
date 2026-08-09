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
