from __future__ import annotations

from typing import Any


def assert_inventory_terminal_state(snapshot: dict[str, Any]) -> None:
    if snapshot.get("dangling_equipment_reference"):
        raise AssertionError("Inventory has a dangling equipped-item reference")

