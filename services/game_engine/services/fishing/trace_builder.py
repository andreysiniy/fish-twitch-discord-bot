"""Build the JSON snapshots stored on a fishing cast from an engine result."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from domain.schemas.fishing import FishingResult
from infrastructure.models import UserProgress


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def build_result_snapshot(result: FishingResult) -> dict:
    """Normalized engine result used for diagnostics and idempotent replay."""
    return _jsonable(
        {
            "loot": result.loot,
            "item_drop": result.item_drop,
            "xp_gained": result.xp_gained,
            "mass_gained": str(result.mass_gained),
            "is_level_up": result.is_level_up,
            "old_level": result.old_level,
            "new_level": result.new_level,
            "luck_used": str(result.luck_used),
            "durability_loss": result.durability_loss,
            "broken_item_name": result.broken_item_name,
            "robbery_result": (
                result.robbery_result.model_dump(mode="json")
                if result.robbery_result
                else None
            ),
            "roulette_result": (
                result.roulette_result.model_dump(mode="json")
                if result.roulette_result
                else None
            ),
        }
    )


def build_rng_trace(result: FishingResult) -> list[dict]:
    """Return the traced RNG stages produced by the engine during the cast."""
    stages = list(result.rng_stages or [])
    if result.reward_roll_trace and not any(
        stage.get("stage") == "ordinary_reward" for stage in stages
    ):
        stages.insert(
            0,
            {
                "stage": "ordinary_reward",
                "algorithm": "weighted_choice_v2",
                "roll": result.reward_roll_trace.get("roll"),
                "total_weight": result.reward_roll_trace.get("total_weight"),
                "selected_reward_id": result.reward_roll_trace.get("selected_id"),
                "selected_probability": result.reward_roll_trace.get("selected_probability"),
            },
        )
    return _jsonable(stages)


def build_equipped_items_snapshot(user: UserProgress) -> list[dict]:
    """Best-effort snapshot of equipped items and their durability."""
    result: list[dict] = []
    for record in getattr(user, "equipped_items", None) or []:
        item = record.inventory_item
        definition = item.definition if item else None
        result.append(
            {
                "slot": record.slot,
                "inventory_item_id": item.id if item else None,
                "item_id": definition.item_id if definition else None,
                "title": definition.title if definition else None,
                "current_durability": item.current_durability if item else None,
            }
        )
    return result


def build_special_result(result: FishingResult) -> dict:
    """Capture robbery/roulette/other special results for the ledger."""
    special: dict[str, Any] = {}
    if result.robbery_result is not None:
        special["robbery"] = result.robbery_result.model_dump(mode="json")
    if result.roulette_result is not None:
        special["roulette"] = result.roulette_result.model_dump(mode="json")
    return _jsonable(special)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_json(value: Any) -> str:
    return json.dumps(_jsonable(value), separators=(",", ":"), ensure_ascii=False)
