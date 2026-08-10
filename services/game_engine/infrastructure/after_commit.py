"""After-commit hooks for deferred cache side effects.

The fishing transaction commits in the FastAPI session dependency (``get_db``).
Gameplay-adjacent cache writes (the Redis fishing cooldown) must only run after
that commit succeeds, otherwise a rolled-back cast would leave Redis-only state
for a cast that never became durable (plan section 16).
"""

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

_CALLBACKS_KEY = "after_commit_callbacks"


def schedule_after_commit(db: Any, callback: Callable[[], None]) -> bool:
    """Register ``callback`` to run after ``db.commit()`` succeeds.

    Returns ``True`` when the hook was registered. Returns ``False`` when the
    session does not expose an ``info`` dict (no transaction wrapper); in that
    case the caller must skip the side effect, never write it eagerly.
    """
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        return False
    info.setdefault(_CALLBACKS_KEY, []).append(callback)
    return True


def run_after_commit_callbacks(db: Any) -> None:
    """Execute and clear the registered after-commit callbacks."""
    info = getattr(db, "info", None)
    if not isinstance(info, dict):
        return
    callbacks = info.pop(_CALLBACKS_KEY, [])
    for callback in callbacks:
        try:
            callback()
        except Exception:
            logger.warning("after-commit callback failed", exc_info=True)
