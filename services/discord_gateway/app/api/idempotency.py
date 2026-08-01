def interaction_key(interaction_id: int | str, operation: str) -> str:
    return f"discord:{interaction_id}:{operation}"
