from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from domain.config_schema import RewardDefinition
from pydantic import TypeAdapter, ValidationError

REWARD_ADAPTER = TypeAdapter(RewardDefinition)


@dataclass(frozen=True)
class LegacyImportResult:
    rewards: list[dict[str, Any]]
    source_counts: dict[str, int]
    target_counts: dict[str, int]
    warnings: list[str]


def convert_legacy_rewards(payload: dict[str, Any]) -> LegacyImportResult:
    groups = payload.get("rewards", payload)
    if not isinstance(groups, dict):
        raise ValueError("Legacy JSON must contain a rewards object")

    converted: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    ignored_fields: set[str] = set()
    warnings: list[str] = []

    for source_type, raw_group in groups.items():
        if source_type not in {
            "nothing",
            "misc",
            "points",
            "percentage_points",
            "russian_roulette",
            "robbery",
            "dupe",
        }:
            warnings.append(f"Unsupported legacy reward group was skipped: {source_type}")
            continue
        entries = raw_group if isinstance(raw_group, list) else [raw_group]
        for index, raw in enumerate(entries, start=1):
            if not isinstance(raw, dict):
                raise ValueError(f"Legacy reward {source_type}[{index}] must be an object")
            source_counts[source_type] += 1
            reward, consumed = _convert_reward(source_type, raw)
            ignored_fields.update(set(raw) - consumed)
            try:
                normalized = REWARD_ADAPTER.validate_python(reward).model_dump(mode="json")
            except ValidationError as error:
                raise ValueError(
                    f"Legacy reward {source_type}[{index}] is invalid: {error.errors()[0]['msg']}"
                ) from error
            converted.append(normalized)
            target_counts[normalized["type"]] += 1

    if not converted:
        raise ValueError("Legacy JSON does not contain supported rewards")
    if ignored_fields:
        warnings.append(
            "Unsupported legacy fields were ignored: " + ", ".join(sorted(ignored_fields))
        )
    if "rewards" in payload:
        top_level_ignored = sorted(set(payload) - {"rewards"})
        if top_level_ignored:
            warnings.append(
                "Legacy channel settings were not imported: " + ", ".join(top_level_ignored)
            )

    return LegacyImportResult(
        rewards=converted,
        source_counts=dict(sorted(source_counts.items())),
        target_counts=dict(sorted(target_counts.items())),
        warnings=warnings,
    )


def _convert_reward(source_type: str, raw: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    reward, consumed = _base_reward(raw)
    if source_type in {"nothing", "misc"}:
        reward["type"] = "nothing"
        return reward, consumed

    if source_type == "points":
        reward.update(
            type="fish",
            fixed_mass=_mass_from_points(raw.get("value")),
            message=_replace_placeholders(reward["message"], {"value": "amount"}),
        )
        return reward, consumed | {"value"}

    if source_type == "percentage_points":
        reward.update(type="fish", percentage=_decimal(raw.get("percentage")))
        return reward, consumed | {"percentage"}

    if source_type == "dupe":
        reward.update(
            type="dupe",
            amount=int(raw.get("amount", 1)),
            delay=int(raw.get("delay", 0)),
        )
        return reward, consumed | {"amount", "delay"}

    if source_type == "robbery":
        reward.update(type="robbery", range=int(raw.get("range", 3)))
        if raw.get("percentage") is not None:
            reward["percentage"] = _decimal(raw["percentage"])
            consumed.add("percentage")
        elif raw.get("value") is not None:
            reward["mass"] = _mass_from_points(raw["value"])
            consumed.add("value")
        else:
            raise ValueError("Legacy robbery reward requires value or percentage")
        success_message = str(raw.get("robbery_message") or "").strip()
        if success_message:
            reward["success_message"] = _replace_placeholders(
                success_message,
                {
                    "username": "attacker",
                    "value": "attacker_gain",
                    "percentage": "attacker_gain",
                },
            )
        return reward, consumed | {"range", "robbery_message"}

    reward.update(
        type="russian_roulette",
        bullets=int(raw.get("bullets", 1)),
        chambers=int(raw.get("chambers", 6)),
        safe_message=_replace_placeholders(str(raw.get("safe_message") or ""), {"value": "amount"}),
        shot_message=_replace_placeholders(str(raw.get("shot_message") or ""), {"value": "amount"}),
    )
    penalty_type = str(raw.get("penalty_type") or "nothing").strip().lower()
    if penalty_type == "points":
        reward["penalty"] = {
            "type": "add_mass",
            "mass": -abs(_mass_from_points(raw.get("value"))),
        }
    elif penalty_type == "percentage":
        reward["penalty"] = {
            "type": "add_percentage_mass",
            "percentage": -abs(_decimal(raw.get("percentage"))),
        }
    elif penalty_type not in {"nothing", "none", ""}:
        raise ValueError(f"Unsupported legacy roulette penalty type: {penalty_type}")
    return reward, consumed | {
        "bullets",
        "chambers",
        "safe_message",
        "shot_message",
        "penalty_type",
        "value",
        "percentage",
    }


def _base_reward(raw: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    reward: dict[str, Any] = {
        "weight": int(raw.get("weight", 1)),
        "xp": int(raw.get("xp", 0)),
        "message": str(raw.get("message") or ""),
    }
    consumed = {"weight", "xp", "message"}
    name = str(raw.get("title") or raw.get("name") or "").strip()
    if name:
        reward["name"] = name
    consumed.update({"title", "name"})
    reward_id = str(raw.get("id") or raw.get("reward_id") or "").strip()
    if reward_id:
        reward["reward_id"] = reward_id
    consumed.update({"id", "reward_id"})
    return reward, consumed


def _mass_from_points(value: Any) -> Decimal:
    return _decimal(value) / Decimal(1000)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"Invalid legacy decimal value: {value}") from error


def _replace_placeholders(message: str, replacements: dict[str, str]) -> str:
    for old, new in replacements.items():
        message = message.replace("{" + old + "}", "{" + new + "}")
    return message
