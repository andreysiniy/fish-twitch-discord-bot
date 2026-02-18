MIN_COOLDOWN_SECONDS = 0
MAX_COOLDOWN_SECONDS = 24 * 60 * 60  # 1 day

MIN_EVENT_DURATION_SECONDS = 1
MAX_EVENT_DURATION_SECONDS = 14 * 24 * 60 * 60  # 2 weeks


def validate_cooldown_seconds(seconds: int) -> int:
    value = int(seconds)
    if value < MIN_COOLDOWN_SECONDS or value > MAX_COOLDOWN_SECONDS:
        raise ValueError(
            f"Cooldown seconds must be between {MIN_COOLDOWN_SECONDS} and {MAX_COOLDOWN_SECONDS}"
        )
    return value


def validate_event_duration_seconds(seconds: int) -> int:
    value = int(seconds)
    if value < MIN_EVENT_DURATION_SECONDS or value > MAX_EVENT_DURATION_SECONDS:
        raise ValueError(
            f"Event duration seconds must be between {MIN_EVENT_DURATION_SECONDS} and {MAX_EVENT_DURATION_SECONDS}"
        )
    return value
