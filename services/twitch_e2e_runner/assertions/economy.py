from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def provider_write_count(requests: dict[str, Any]) -> int:
    return sum(
        1 for item in requests.get("requests", []) if item.get("operation") == "points_write"
    )


def assert_at_most_one_provider_write(requests: dict[str, Any]) -> None:
    count = provider_write_count(requests)
    if count > 1:
        raise AssertionError(f"Expected at most one provider write, got {count}")


def assert_successful_buy(checks: dict[str, Any], command_index: int) -> None:
    """Validate a BUY from durable evidence rather than an uncorrelated chat reply."""

    evidence = checks.get("evidence", [])
    if command_index >= len(evidence):
        raise AssertionError("Successful !fishbuy has no durable operation evidence")
    operation = evidence[command_index]
    if operation.get("state") != "completed":
        raise AssertionError("Successful !fishbuy did not complete the economy operation")
    try:
        points_delta = Decimal(str(operation.get("points_delta", "0")))
        mass_delta = Decimal(str(operation.get("mass_delta", "0")))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise AssertionError("Successful !fishbuy has invalid operation deltas") from error
    if points_delta >= 0 or mass_delta <= 0:
        raise AssertionError("Successful !fishbuy did not debit points and grant mass")
    payload = operation.get("response_payload")
    message = payload.get("chat_message", "") if isinstance(payload, dict) else ""
    if "bought" not in str(message).lower():
        raise AssertionError("Successful !fishbuy has no success response in durable evidence")

