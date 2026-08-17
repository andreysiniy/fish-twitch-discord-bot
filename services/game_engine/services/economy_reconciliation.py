"""Shared local finalization for confirmed StreamElements operations."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from domain.economy import EconomyDomainError
from domain.logic.mass import apply_mass_mutation
from infrastructure.models import EconomyOperation, EconomyOperationEvent, UserProgress


def apply_confirmed_buy_mass(db, operation: EconomyOperation, *, actor_type: str) -> None:
    """Apply a confirmed BUY mass delta exactly once.

    Provider confirmation and local state mutation are separate phases of the
    economy saga. Reconciliation and worker retries can both reach this
    helper, so ``internal_applied_at`` is the durable idempotency guard.
    """

    if operation.operation_type != "buy" or operation.internal_applied_at is not None:
        return

    user = (
        db.query(UserProgress)
        .filter(
            UserProgress.id == operation.user_id,
            UserProgress.channel_id == operation.channel_id,
        )
        .with_for_update()
        .one_or_none()
    )
    if user is None:
        raise EconomyDomainError(
            "ECONOMY_RECONCILIATION_ORPHANED",
            "The local player record for this BUY operation is unavailable.",
        )

    mass_value = operation.mass_effective
    if mass_value is None:
        mass_value = operation.mass_delta
    mass = Decimal(str(mass_value))
    if mass <= 0:
        raise EconomyDomainError(
            "ECONOMY_RECONCILIATION_INVALID_MASS",
            "The confirmed BUY operation has no positive mass to apply.",
        )

    apply_mass_mutation(user, mass, track_total=True)
    operation.player_mass_after = Decimal(str(user.current_mass))
    operation.internal_applied_at = datetime.now(timezone.utc)

    db.flush()
    last_sequence = (
        db.query(EconomyOperationEvent.sequence_no)
        .filter(EconomyOperationEvent.operation_id == operation.id)
        .order_by(EconomyOperationEvent.sequence_no.desc())
        .first()
    )
    db.add(
        EconomyOperationEvent(
            operation_id=operation.id,
            sequence_no=(last_sequence[0] if last_sequence else 0) + 1,
            event_type="local_mass_applied",
            from_state="external_applied",
            to_state="completed",
            actor_type=actor_type,
            event_metadata={"mass": str(mass)},
        )
    )
