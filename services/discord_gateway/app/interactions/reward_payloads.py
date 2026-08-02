from decimal import Decimal
from typing import Any

from app.presentation.formatting import parse_decimal, parse_duration

REWARD_TYPES = {"fish", "timeout", "robbery", "russian_roulette", "dupe", "nothing"}
OUTCOME_TYPES = {"add_mass", "add_percentage_mass", "timeout"}


def build_reward_base_payload(
    reward_type: str,
    name: str,
    weight: str,
    xp: str,
    message: str,
) -> dict[str, Any]:
    if reward_type not in REWARD_TYPES:
        raise ValueError("Unknown reward type")
    parsed_weight = _bounded_int(weight, "Weight", 1, 1_000_000)
    parsed_xp = _bounded_int(xp or "0", "XP", 0, 1_000_000)
    payload: dict[str, Any] = {
        "type": reward_type,
        "weight": parsed_weight,
        "xp": parsed_xp,
        "message": message.strip(),
    }
    if name.strip():
        payload["name"] = name.strip()
    return payload


def complete_reward_payload(
    base_payload: dict[str, Any],
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(base_payload)
    values = parameters or {}
    reward_type = payload["type"]

    if reward_type == "fish":
        fixed_mass = _optional_decimal(
            values.get("fixed_mass"), "Fixed mass", -1_000_000, 1_000_000
        )
        min_mass = _optional_decimal(
            values.get("min_mass"), "Minimum mass", -1_000_000, 1_000_000
        )
        max_mass = _optional_decimal(
            values.get("max_mass"), "Maximum mass", -1_000_000, 1_000_000
        )
        percentage = _optional_decimal(values.get("percentage"), "Percentage", -1, 1)
        has_range = min_mass is not None or max_mass is not None
        if sum((fixed_mass is not None, has_range, percentage is not None)) != 1:
            raise ValueError("Choose exactly one fish mass mode: fixed, range, or percentage")
        if has_range:
            if min_mass is None or max_mass is None:
                raise ValueError("Both minimum and maximum mass are required for a range")
            if Decimal(min_mass) > Decimal(max_mass):
                raise ValueError("Minimum mass must not exceed maximum mass")
            payload.update({"min_mass": min_mass, "max_mass": max_mass})
        elif fixed_mass is not None:
            payload["fixed_mass"] = fixed_mass
        else:
            payload["percentage"] = percentage
    elif reward_type == "timeout":
        payload["duration"] = parse_duration(str(values.get("duration") or ""))
        payload["reason"] = str(values.get("reason") or "").strip()
    elif reward_type == "robbery":
        mass = _optional_decimal(values.get("mass"), "Fixed mass", 0, 1_000_000)
        percentage = _optional_decimal(values.get("percentage"), "Percentage", 0, 1)
        if (mass is None) == (percentage is None):
            raise ValueError("Choose exactly one robbery amount: fixed mass or percentage")
        if mass is not None:
            payload["mass"] = mass
        else:
            payload["percentage"] = percentage
        payload["range"] = _bounded_int(
            str(values.get("range") or "3"), "Victim search range", 1, 100
        )
        payload["success_message"] = str(values.get("success_message") or "").strip()
    elif reward_type == "russian_roulette":
        bullets = _bounded_int(str(values.get("bullets") or "1"), "Bullets", 1, 6)
        chambers = _bounded_int(str(values.get("chambers") or "6"), "Chambers", 1, 100)
        if bullets > chambers:
            raise ValueError("Bullets must not exceed chambers")
        payload.update(
            {
                "bullets": bullets,
                "chambers": chambers,
                "safe_message": str(values.get("safe_message") or "").strip(),
                "shot_message": str(values.get("shot_message") or "").strip(),
            }
        )
        if values.get("reward") is not None:
            payload["reward"] = values["reward"]
        if values.get("penalty") is not None:
            payload["penalty"] = values["penalty"]
    elif reward_type == "dupe":
        payload["amount"] = _bounded_int(
            str(values.get("amount") or "1"), "Repeat count", 1, 20
        )
        payload["delay"] = _bounded_int(
            str(values.get("delay") or "0"), "Delay", 0, 60
        )
    elif reward_type != "nothing":
        raise ValueError("Unknown reward type")
    return payload


def build_reward_payload(
    reward_type: str,
    name: str,
    weight: str,
    xp: str,
    message: str,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = build_reward_base_payload(reward_type, name, weight, xp, message)
    return complete_reward_payload(base, parameters)


def build_roulette_outcome(
    outcome_type: str,
    mass: str,
    percentage: str,
    duration: str,
    reason: str,
) -> dict[str, Any] | None:
    normalized_type = outcome_type.strip().lower()
    if normalized_type in {"", "none"}:
        return None
    if normalized_type not in OUTCOME_TYPES:
        raise ValueError("Effect type must be add_mass, add_percentage_mass, timeout, or none")
    if normalized_type == "add_mass":
        return {
            "type": normalized_type,
            "mass": _required_decimal(mass, "Mass", -1_000_000, 1_000_000),
        }
    if normalized_type == "add_percentage_mass":
        return {
            "type": normalized_type,
            "percentage": _required_decimal(percentage, "Percentage", -1, 1),
        }
    return {
        "type": normalized_type,
        "duration": parse_duration(duration),
        "reason": reason.strip(),
    }


def _bounded_int(value: str, label: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value.strip())
    except ValueError as error:
        raise ValueError(f"{label} must be an integer") from error
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return parsed


def _required_decimal(
    value: str,
    label: str,
    minimum: int | Decimal,
    maximum: int | Decimal,
) -> str:
    parsed = parse_decimal(value)
    decimal = Decimal(parsed)
    if not Decimal(str(minimum)) <= decimal <= Decimal(str(maximum)):
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return parsed


def _optional_decimal(
    value: Any,
    label: str,
    minimum: int | Decimal,
    maximum: int | Decimal,
) -> str | None:
    if value is None or not str(value).strip():
        return None
    return _required_decimal(str(value), label, minimum, maximum)
