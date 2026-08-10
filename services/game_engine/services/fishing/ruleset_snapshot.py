"""Build canonical ruleset snapshots and stable content hashes for the cast ledger."""

import hashlib
import json
from typing import Any

from infrastructure.models import RewardPool, UserProgress


def _canonical_json(value: Any) -> str:
    """Serialize to canonical JSON that is stable for key ordering and spacing."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def hash_payload(payload: dict) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _safe_reward_entry(entry: dict) -> dict:
    """Keep only persistent, deterministic reward fields for the snapshot."""
    allowed = {
        "type",
        "weight",
        "value",
        "percentage",
        "fixed_mass",
        "mass",
        "min_mass",
        "max_mass",
        "xp",
        "points",
        "message",
        "bullets",
        "chambers",
        "shot_message",
        "safe_message",
        "penalty",
        "reward",
        "range",
        "identifier",
        "extra_data",
    }
    return {key: entry[key] for key in allowed if key in entry}


def build_ruleset_snapshot_payload(
    *,
    user: UserProgress,
    pool: RewardPool | None,
    rewards: list[dict],
    item_entries: list[dict],
    items_drop_rate: float,
    channel_config_version: int,
    modifier_schema_version: int,
    engine_version: str,
    event_snapshot: dict,
    effective_params_snapshot: dict,
    item_loot_table_id: int | None = None,
    item_loot_table_version: int | None = None,
) -> dict:
    """Assemble the canonical snapshot of static rules applied to a cast."""
    location_id = user.current_location_id or "default"
    payload = {
        "location": {
            "location_id": location_id,
            "location_name": pool.location_name if pool else None,
        },
        "channel_config_version": channel_config_version,
        "items_drop_rate": str(items_drop_rate),
        "item_loot_table_id": item_loot_table_id,
        "item_loot_table_version": item_loot_table_version,
        "reward_entries": [_safe_reward_entry(entry) for entry in rewards],
        "item_entries": [
            {
                "db_id": entry.get("db_id"),
                "item_definition_id": entry.get("item_definition_id"),
                "item_id": entry.get("item_id"),
                "weight": entry.get("weight"),
                "rarity": entry.get("rarity"),
                "definition_version": entry.get("definition_version"),
                "item_type": entry.get("item_type"),
                "min_quantity": entry.get("min_quantity"),
                "max_quantity": entry.get("max_quantity"),
                "remaining_stock": entry.get("remaining_stock"),
            }
            for entry in item_entries
        ],
        "event": event_snapshot,
        "effective_params": effective_params_snapshot,
        "modifier_schema_version": modifier_schema_version,
    }
    return payload


def snapshot_hash(payload: dict) -> str:
    return hash_payload(payload)
