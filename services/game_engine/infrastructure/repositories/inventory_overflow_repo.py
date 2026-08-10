"""Durable overflow (mailbox) storage for drops that did not fit an inventory.

When a normal ``InventoryRepository.grant_many`` raises ``InventoryCapacityError``
a finite-stock drop is parked here and counted as delivered (plan section 10).
An administrator reclaims parked rows through the Discord claim flow; rows stay
tenant-safe because the model carries the same composite FKs as ``InventoryItem``.
"""

from sqlalchemy.orm import Session

from infrastructure.models import InventoryOverflowItem, UserProgress


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
        return (
            self.db.query(InventoryOverflowItem)
            .filter(
                InventoryOverflowItem.user_id == user_id,
                InventoryOverflowItem.status == "parked",
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
            )
            .with_for_update(of=InventoryOverflowItem)
            .first()
        )
