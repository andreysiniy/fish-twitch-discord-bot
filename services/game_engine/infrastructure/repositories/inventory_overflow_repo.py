"""Durable overflow (mailbox) storage for drops that did not fit an inventory.

When a normal ``InventoryRepository.grant_many`` raises ``InventoryCapacityError``
a finite-stock drop is parked here and counted as delivered (plan section 10).
An administrator reclaims parked rows through the Discord claim flow; rows stay
tenant-safe because the model carries the same composite FKs as ``InventoryItem``.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from infrastructure.models import InventoryOverflowItem, UserProgress
from sqlalchemy.orm import Session

OVERFLOW_TTL = timedelta(hours=24)


class InventoryOverflowRepository:
    def __init__(self, db: Session):
        self.db = db

    def park(
        self,
        *,
        user: UserProgress,
        item_definition_id: int,
        quantity: int,
        source_type: str = "fishing_cast",
        source_id: str | None = None,
    ) -> InventoryOverflowItem:
        """Create a durable parked row for one undelivered drop."""
        row = InventoryOverflowItem(
            channel_id=user.channel_id,
            user_id=user.id,
            item_definition_id=item_definition_id,
            quantity=quantity,
            source_type=source_type,
            source_id=source_id,
            status="parked",
            version=1,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def list_parked(self, user_id: int) -> list[InventoryOverflowItem]:
        cutoff = datetime.now(timezone.utc) - OVERFLOW_TTL
        return (
            self.db.query(InventoryOverflowItem)
            .filter(
                InventoryOverflowItem.user_id == user_id,
                InventoryOverflowItem.status == "parked",
                InventoryOverflowItem.created_at > cutoff,
            )
            .order_by(InventoryOverflowItem.created_at.asc())
            .all()
        )

    def get_parked_for_update(self, user_id: int, overflow_id: int) -> InventoryOverflowItem | None:
        """Lock one still-parked row for a claim, or ``None`` when absent.

        The ``FOR UPDATE`` lock is taken outside any savepoint so a failed
        grant inside ``grant_many`` (which rolls back only its own savepoint)
        cannot release the claim's lock.
        """
        return (
            self.db.query(InventoryOverflowItem)
            .filter(
                InventoryOverflowItem.id == overflow_id,
                InventoryOverflowItem.user_id == user_id,
                InventoryOverflowItem.status == "parked",
                InventoryOverflowItem.created_at
                > datetime.now(timezone.utc) - OVERFLOW_TTL,
            )
            .with_for_update(of=InventoryOverflowItem)
            .first()
        )

    def claim_available(
        self, *, user: UserProgress, inventory_repo: Any
    ) -> list[InventoryOverflowItem]:
        """Deliver the oldest parked rows that now fit in the inventory.

        The caller locks the user before invoking this method. Overflow rows
        are then locked in creation order, matching the administrator claim
        flow and preventing concurrent delivery of the same row.
        """
        from infrastructure.repositories.inventory_repo import InventoryCapacityError

        claimed: list[InventoryOverflowItem] = []
        for pending in self.list_parked(user.id):
            row = self.get_parked_for_update(user.id, pending.id)
            if row is None:
                continue
            if row.definition is None:
                continue
            try:
                inventory_repo.grant_many(
                    user,
                    [{"item_id": row.definition.item_id, "quantity": row.quantity, "meta": {}}],
                )
            except InventoryCapacityError:
                break
            except ValueError:
                # Keep malformed or archived rows parked for an administrator
                # to inspect; a later valid row may still fit.
                continue
            row.status = "claimed"
            row.version += 1
            row.claimed_at = datetime.now(timezone.utc)
            self.db.flush()
            claimed.append(row)
        return claimed

    def delete_expired(self, *, now: datetime) -> int:
        """Delete parked rows after their 24-hour mailbox retention period."""
        cutoff = now - OVERFLOW_TTL
        return (
            self.db.query(InventoryOverflowItem)
            .filter(
                InventoryOverflowItem.status == "parked",
                InventoryOverflowItem.created_at <= cutoff,
            )
            .delete(synchronize_session=False)
        )
