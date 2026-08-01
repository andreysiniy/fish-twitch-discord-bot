import re
from decimal import Decimal, InvalidOperation
from typing import Any

DURATION_PATTERN = re.compile(r"^(?P<value>[1-9]\d*)(?P<unit>[smhd]?)$", re.IGNORECASE)
DURATION_MULTIPLIERS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86_400}


def parse_duration(value: str, maximum: int = 1_209_600) -> int:
    match = DURATION_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError("Use seconds or a duration such as 10m, 2h, or 1d")
    seconds = int(match.group("value")) * DURATION_MULTIPLIERS[match.group("unit").lower()]
    if seconds > maximum:
        raise ValueError(f"Maximum duration is {maximum} seconds")
    return seconds


def parse_decimal(value: str) -> str:
    normalized = value.strip().replace(",", ".")
    try:
        decimal = Decimal(normalized)
    except InvalidOperation as error:
        raise ValueError("A number is required") from error
    if not decimal.is_finite():
        raise ValueError("NaN and Infinity are not allowed")
    return format(decimal, "f")


def format_percent(value: Any) -> str:
    return f"{Decimal(str(value)) * 100:g}%"


def diff_lines(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    lines = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            lines.append(f"- `{key}`: `{before.get(key)}` -> `{after.get(key)}`")
    return lines
