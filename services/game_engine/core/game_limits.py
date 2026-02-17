MIN_COOLDOWN_SECONDS = 0
MAX_COOLDOWN_SECONDS = 24 * 60 * 60  # 1 day


def validate_cooldown_seconds(seconds: int) -> int:
    value = int(seconds)
    if value < MIN_COOLDOWN_SECONDS or value > MAX_COOLDOWN_SECONDS:
        raise ValueError(
            f"Cooldown seconds must be between {MIN_COOLDOWN_SECONDS} and {MAX_COOLDOWN_SECONDS}"
        )
    return value
