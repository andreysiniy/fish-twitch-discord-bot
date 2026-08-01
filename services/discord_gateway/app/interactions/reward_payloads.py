from typing import Any

from app.presentation.formatting import parse_decimal, parse_duration


def build_reward_payload(
    reward_type: str,
    name: str,
    weight: str,
    xp: str,
    message: str,
    parameters: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": reward_type,
        "weight": int(weight),
        "xp": int(xp or 0),
        "message": message,
    }
    if name.strip():
        payload["name"] = name.strip()
    values = _parse_parameters(parameters)
    if reward_type == "fish":
        if "fixed" in values:
            payload["fixed_mass"] = parse_decimal(values["fixed"])
        elif "percentage" in values:
            payload["percentage"] = parse_decimal(values["percentage"])
        elif "range" in values:
            parts = [part.strip() for part in values["range"].split(",")]
            if len(parts) != 2:
                raise ValueError("Use range=0.1,5 for a mass range")
            payload["min_mass"] = parse_decimal(parts[0])
            payload["max_mass"] = parse_decimal(parts[1])
        else:
            raise ValueError("For fish, use fixed=1, range=0.1,5, or percentage=0.1")
    elif reward_type == "timeout":
        payload["duration"] = parse_duration(values.get("duration", ""))
        payload["reason"] = values.get("reason", "")
    elif reward_type == "robbery":
        if "percentage" in values:
            payload["percentage"] = parse_decimal(values["percentage"])
        elif "mass" in values:
            payload["mass"] = parse_decimal(values["mass"])
        else:
            raise ValueError("For robbery, use percentage=0.1 or mass=1")
        if "range" in values:
            payload["range"] = int(values["range"])
    elif reward_type == "russian_roulette":
        payload["bullets"] = int(values.get("bullets", "1"))
        payload["chambers"] = int(values.get("chambers", "6"))
        payload["safe_message"] = values.get("safe", "")
        payload["shot_message"] = values.get("shot", "")
    elif reward_type != "nothing":
        raise ValueError("Unknown reward type")
    return payload


def _parse_parameters(value: str) -> dict[str, str]:
    result = {}
    for chunk in value.split(";"):
        if not chunk.strip():
            continue
        key, separator, raw_value = chunk.partition("=")
        if not separator or not key.strip() or not raw_value.strip():
            raise ValueError("Use key=value;key=value for parameters")
        result[key.strip().lower()] = raw_value.strip()
    return result
