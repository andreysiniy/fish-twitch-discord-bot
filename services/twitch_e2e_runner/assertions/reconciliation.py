from __future__ import annotations

from typing import Any


def assert_reconciliation_required(evidence: dict[str, Any]) -> None:
    if evidence.get("available") and evidence.get("state") != "reconciliation_required":
        raise AssertionError("Ambiguous provider write did not enter reconciliation_required")

