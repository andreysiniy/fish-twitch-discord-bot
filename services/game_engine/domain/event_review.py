"""Pure validation helpers for event modifiers that require owner review."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

# These are the same absolute limits used when the v2 migration marks an event
# for review. Keep the values here (rather than importing a migration) so the
# runtime can explain a persisted review flag without coupling to Alembic.
EVENT_REVIEW_LIMITS: tuple[tuple[str, str, Decimal], ...] = (
    ("positive_fish_reward_change_percent", "Good Catch", Decimal("200")),
    ("xp_gain_change_percent", "XP", Decimal("200")),
    ("fish_luck_change_percent", "Fish Luck", Decimal("200")),
)


def event_review_issues(modifiers: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """Return concrete, user-facing reasons an event must be reviewed.

    Review flags can survive migrations and old payloads, so values are parsed
    defensively instead of assuming the current Pydantic schema was used.
    """

    if not modifiers:
        return []

    issues: list[dict[str, str]] = []
    for field, label, limit in EVENT_REVIEW_LIMITS:
        raw = modifiers.get(field)
        if raw is None:
            continue
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            issues.append(
                {
                    "field": field,
                    "label": label,
                    "value": str(raw),
                    "limit": f"+/- {limit}%",
                    "message": f"{label} must be a valid percentage.",
                }
            )
            continue
        if abs(value) <= limit:
            continue
        displayed = _format_percent(value)
        issues.append(
            {
                "field": field,
                "label": label,
                "value": displayed,
                "limit": f"+/- {limit}%",
                "message": (
                    f"{label} is {displayed}, beyond the safe limit of +/- {limit}%."
                ),
            }
        )
    return issues


def event_review_error_message(modifiers: Mapping[str, Any] | None) -> str:
    """Build the detailed message used by the legacy Twitch API path."""

    issues = event_review_issues(modifiers)
    if not issues:
        return (
            "Event cannot be activated because it requires review. "
            "Review and save its modifiers before trying again."
        )
    details = " ".join(issue["message"] for issue in issues)
    return (
        "Event cannot be activated because it requires review. "
        f"{details} Adjust the listed modifiers and save the event before trying again."
    )


def _format_percent(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if value > 0 and not rendered.startswith("+"):
        rendered = f"+{rendered}"
    return f"{rendered}%"
