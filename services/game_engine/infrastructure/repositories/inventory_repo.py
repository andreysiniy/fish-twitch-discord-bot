import random
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from domain.logic.mass import apply_mass_mutation
from infrastructure.models import (
    EquippedItem,
    InventoryItem,
    InventoryItemUseRecord,
    ItemDefinition,
    OutboxEvent,
    UserProgress,
)
from infrastructure.repositories.inventory_overflow_repo import InventoryOverflowRepository
from services.loot_table_service import LootTableRollService


class InventoryCapacityError(ValueError):
    pass


class InventoryRepository:
    def __init__(
        self,
        db: Session,
        rng: random.Random | None = None,
        max_slots_add: int = 0,
    ):
        self.db = db
        self.rng = rng or random.SystemRandom()
        self.max_slots_add = int(max_slots_add)

    def grant_many(self, user: UserProgress, grants: list[dict[str, Any]]) -> list[InventoryItem]:
        with self.db.begin_nested():
            return self._grant_many_locked(user, grants)

    def _grant_many_locked(
        self, user: UserProgress, grants: list[dict[str, Any]]
    ) -> list[InventoryItem]:
        if not grants:
            return []
        locked_user = self._lock_user(user.id)
        items = self._lock_items(locked_user.id)
        definitions = self._load_definitions(locked_user.channel_id, grants)
        max_slots = self._max_slots(locked_user)
        touched: list[InventoryItem] = []

        for grant in grants:
            item_key = str(grant.get("item_id") or "").strip()
            definition = definitions[item_key]
            quantity = int(grant.get("quantity", 1))
            if quantity <= 0:
                raise ValueError("Item quantity must be positive")
            explicit_slot = grant.get("slot_id")
            if explicit_slot is not None:
                explicit_slot = int(explicit_slot)
                if explicit_slot < 1 or explicit_slot > max_slots:
                    raise InventoryCapacityError(
                        f"Inventory slot must be between 1 and {max_slots}"
                    )
            durability = self._resolve_durability(definition, grant.get("current_durability"))
            charges = self._resolve_charges(definition, grant.get("current_charges"))
            meta = dict(grant.get("meta") or {})
            touched.extend(
                self._place_grant(
                    locked_user,
                    items,
                    definition,
                    quantity,
                    max_slots,
                    explicit_slot,
                    durability,
                    charges,
                    meta,
                )
            )

        self.db.flush()
        for item in touched:
            self.db.refresh(item)
        return list(dict.fromkeys(touched))

    def get_equipped(self, user_id: int) -> list[EquippedItem]:
        return (
            self.db.query(EquippedItem)
            .filter(EquippedItem.user_id == user_id)
            .order_by(EquippedItem.slot.asc())
            .all()
        )

    def equip(self, user_id: int, inventory_slot: int, target_slot: str | None = None) -> EquippedItem:
        user = self._lock_user(user_id)
        item = (
            self.db.query(InventoryItem)
            .filter(InventoryItem.user_id == user.id, InventoryItem.slot_id == inventory_slot)
            .with_for_update(of=InventoryItem)
            .first()
        )
        if not item or not item.definition:
            raise ValueError(f"Inventory slot {inventory_slot} is empty")
        definition = item.definition
        if definition.type != "equipment" or not definition.slot:
            raise ValueError(f"{definition.title} is not equipment")
        equipment_slot = target_slot or definition.slot
        if equipment_slot != definition.slot:
            raise ValueError(f"{definition.title} can only be equipped in {definition.slot}")
        if item.current_durability is not None and item.current_durability <= 0:
            raise ValueError(f"{definition.title} is broken")

        equipped = (
            self.db.query(EquippedItem)
            .filter(EquippedItem.user_id == user.id, EquippedItem.slot == equipment_slot)
            .with_for_update(of=EquippedItem)
            .first()
        )
        if equipped:
            equipped.inventory_item_id = item.id
        else:
            equipped = EquippedItem(
                user_id=user.id,
                slot=equipment_slot,
                inventory_item_id=item.id,
            )
            self.db.add(equipped)

        self.db.flush()
        self.db.refresh(equipped)
        return equipped

    def unequip(self, user_id: int, equipment_slot: str) -> None:
        user = self._lock_user(user_id)
        equipped = (
            self.db.query(EquippedItem)
            .filter(EquippedItem.user_id == user.id, EquippedItem.slot == equipment_slot)
            .with_for_update(of=EquippedItem)
            .first()
        )
        if equipped:
            self.db.delete(equipped)
        self.db.flush()

    def consume_durability(self, user_id: int, equipment_slot: str, amount: int) -> str | None:
        if amount <= 0:
            return None
        user = self._lock_user(user_id)
        equipped = (
            self.db.query(EquippedItem)
            .filter(EquippedItem.user_id == user.id, EquippedItem.slot == equipment_slot)
            .with_for_update(of=EquippedItem)
            .first()
        )
        if not equipped:
            return None
        item = (
            self.db.query(InventoryItem)
            .filter(InventoryItem.id == equipped.inventory_item_id)
            .with_for_update(of=InventoryItem)
            .first()
        )
        if not item or item.current_durability is None or not item.definition:
            return None
        previous = int(item.current_durability)
        if previous <= 0:
            # Already broken: retain_broken keeps the rod equipped at zero, but
            # the break must be announced only once, on the transition to zero.
            return None
        item.current_durability = max(previous - amount, 0)
        item.version += 1
        if item.current_durability > 0:
            self.db.flush()
            return None

        title = item.definition.title
        policy = item.definition.break_policy
        if policy == "destroy_at_zero":
            self.db.delete(item)
        elif policy == "unequip_broken":
            self.db.delete(equipped)
        self.db.flush()
        return title

    def use_item(
        self,
        user: UserProgress,
        inventory_slot: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise ValueError("Idempotency key is required")
        replay = (
            self.db.query(InventoryItemUseRecord)
            .filter(
                InventoryItemUseRecord.user_id == user.id,
                InventoryItemUseRecord.idempotency_key == idempotency_key,
            )
            .first()
        )
        if replay:
            return dict(replay.response_json)

        locked_user = self._lock_user(user.id)
        replay = (
            self.db.query(InventoryItemUseRecord)
            .filter(
                InventoryItemUseRecord.user_id == locked_user.id,
                InventoryItemUseRecord.idempotency_key == idempotency_key,
            )
            .first()
        )
        if replay:
            return dict(replay.response_json)
        item = (
            self.db.query(InventoryItem)
            .filter(InventoryItem.user_id == locked_user.id, InventoryItem.slot_id == inventory_slot)
            .with_for_update(of=InventoryItem)
            .first()
        )
        if not item or not item.definition:
            raise ValueError(f"Inventory slot {inventory_slot} is empty")
        definition = item.definition
        if definition.type not in {"consumable", "lootbox"}:
            raise ValueError(f"{definition.title} cannot be used")

        consumed_item_id = item.id
        # The use record must be inserted while the consumed item row still
        # exists so the FK holds; deleting the item afterwards nulls the
        # reference (SET NULL) but keeps the idempotent replay row intact.
        use_record = InventoryItemUseRecord(
            id=str(uuid.uuid4()),
            user_id=locked_user.id,
            inventory_item_id=consumed_item_id,
            idempotency_key=idempotency_key,
            response_json={},
        )
        self.db.add(use_record)
        self.db.flush()

        if definition.max_charges is not None:
            # Charge-based consumable (spec 11.4): a use consumes the amount
            # declared by the consume_charge effect instead of a stack quantity;
            # the instance is deleted when charges run out.
            charge_amount = 1
            for effect in definition.effects or []:
                if effect.get("type") == "consume_charge":
                    charge_amount = max(int(effect.get("amount", 1)), 1)
                    break
            item.current_charges = int(item.current_charges or 0) - charge_amount
            if item.current_charges <= 0:
                self.db.delete(item)
            else:
                item.version += 1
        else:
            # Single-use consumable: use consumes one item from the stack.
            item.quantity -= 1
            if item.quantity == 0:
                self.db.delete(item)
            else:
                item.version += 1
        self.db.flush()

        grants: list[dict[str, Any]] = []
        granted: list[InventoryItem] = []
        loot_resolutions: list[Any] = []
        mass_delta = Decimal("0")
        actions: list[dict[str, Any]] = []
        for effect in definition.effects or []:
            effect_type = effect.get("type")
            if effect_type == "grant_item":
                grants.append(
                    {"item_id": effect["item_id"], "quantity": int(effect.get("quantity", 1))}
                )
            elif effect_type == "grant_mass":
                mass_delta += Decimal(str(effect["mass"]))
            elif effect_type == "apply_timeout":
                action = {
                    "type": "timeout",
                    "duration_seconds": int(effect["duration_seconds"]),
                    "reason": effect.get("reason", "Item effect"),
                    "target_user": locked_user.username,
                }
                actions.append(action)
            elif effect_type == "loot_table_roll":
                delivered, resolutions = self._roll_loot_table(
                        locked_user.channel_id,
                        str(effect["loot_table_id"]),
                        int(effect.get("rolls", 1)),
                        user=locked_user,
                        source_id=idempotency_key,
                    )
                granted.extend(delivered)
                loot_resolutions.extend(resolutions)

        if grants:
            granted.extend(self.grant_many(locked_user, grants))
        apply_mass_mutation(locked_user, mass_delta, track_total=True)
        for index, action in enumerate(actions):
            self.db.add(
                OutboxEvent(
                    id=str(uuid.uuid4()),
                    idempotency_key=f"item-use:{idempotency_key}:{index}",
                    topic="external_action",
                    payload={
                        **action,
                        "channel_id": locked_user.channel_id,
                        "user_twitch_id": locked_user.user_twitch_id,
                    },
                )
            )

        response = {
            "success": True,
            "item_id": definition.item_id,
            "item_title": definition.title,
            "mass_delta": str(mass_delta),
            "granted_items": [
                {
                    "item_id": granted_item.definition.item_id,
                    "quantity": granted_item.quantity,
                    "slot_id": granted_item.slot_id,
                }
                for granted_item in granted
            ],
            "loot_resolutions": [
                resolution.model_dump(mode="json") for resolution in loot_resolutions
            ],
            "actions": actions,
        }
        use_record.response_json = response
        self.db.flush()
        return response

    def _place_grant(
        self,
        user: UserProgress,
        items: list[InventoryItem],
        definition: ItemDefinition,
        quantity: int,
        max_slots: int,
        explicit_slot: int | None,
        durability: int | None,
        charges: int | None,
        meta: dict[str, Any],
    ) -> list[InventoryItem]:
        touched: list[InventoryItem] = []
        remaining = quantity
        stack_size = int(definition.stack_size)
        can_stack = stack_size > 1 and definition.type != "equipment"

        if explicit_slot is not None:
            occupied = next((candidate for candidate in items if candidate.slot_id == explicit_slot), None)
            if occupied and not (
                can_stack
                and occupied.item_id == definition.id
                and occupied.meta == meta
                and occupied.current_durability == durability
                and occupied.current_charges == charges
            ):
                raise InventoryCapacityError(f"Inventory slot {explicit_slot} is occupied")
            candidates = [occupied] if occupied else []
        else:
            candidates = [
                candidate
                for candidate in items
                if can_stack
                and candidate.item_id == definition.id
                and candidate.meta == meta
                and candidate.current_durability == durability
                and candidate.current_charges == charges
                and candidate.quantity < stack_size
            ]

        for candidate in candidates:
            if not candidate:
                continue
            added = min(stack_size - candidate.quantity, remaining)
            candidate.quantity += added
            candidate.version += 1
            remaining -= added
            touched.append(candidate)
            if remaining == 0:
                return touched

        occupied_slots = {candidate.slot_id for candidate in items}
        while remaining > 0:
            if explicit_slot is not None and explicit_slot not in occupied_slots:
                slot_id = explicit_slot
                explicit_slot = None
            else:
                slot_id = next(
                    (slot for slot in range(1, max_slots + 1) if slot not in occupied_slots),
                    None,
                )
            if slot_id is None:
                raise InventoryCapacityError(f"Inventory is full ({max_slots} slots)")
            stack_quantity = min(stack_size, remaining) if can_stack else 1
            created = InventoryItem(
                user_id=user.id,
                channel_id=user.channel_id,
                item_id=definition.id,
                slot_id=slot_id,
                quantity=stack_quantity,
                current_durability=durability,
                current_charges=charges,
                meta=meta,
                definition_version=definition.version,
            )
            self.db.add(created)
            self.db.flush()
            items.append(created)
            touched.append(created)
            occupied_slots.add(slot_id)
            remaining -= stack_quantity
        return touched

    def _load_definitions(
        self, channel_id: int, grants: list[dict[str, Any]]
    ) -> dict[str, ItemDefinition]:
        keys = {str(grant.get("item_id") or "").strip() for grant in grants}
        if "" in keys:
            raise ValueError("item_id is required")
        rows = (
            self.db.query(ItemDefinition)
            .filter(
                ItemDefinition.channel_id == channel_id,
                ItemDefinition.item_id.in_(keys),
                ItemDefinition.is_active.is_(True),
            )
            .all()
        )
        definitions = {row.item_id: row for row in rows}
        missing = sorted(keys - definitions.keys())
        if missing:
            raise ValueError(f"Active item definition not found: {', '.join(missing)}")
        return definitions

    def _roll_loot_table(
        self,
        channel_id: int,
        table_id: str,
        rolls: int,
        *,
        user: UserProgress,
        source_id: str,
    ) -> tuple[list[InventoryItem], list[Any]]:
        service = LootTableRollService(self.db)
        resolutions = service.roll(channel_id, table_id, rolls=rolls)
        delivered: list[InventoryItem] = []
        overflow_repo = InventoryOverflowRepository(self.db)
        for resolution in resolutions:
            quantity = int(resolution.quantity_granted or 0)
            if quantity <= 0:
                continue
            try:
                rows = self.grant_many(
                    user,
                    [{"item_id": resolution.item_id, "quantity": quantity}],
                )
            except InventoryCapacityError:
                if resolution.item_definition_id is None:
                    resolution.status = "failed"
                    resolution.failure_reason = "item definition is unavailable"
                    continue
                overflow_repo.park(
                    user=user,
                    item_definition_id=resolution.item_definition_id,
                    quantity=quantity,
                    source_type="lootbox",
                    source_id=source_id,
                )
                resolution.status = "overflowed"
                resolution.delivery_target = "overflow"
                resolution.quantity_granted = quantity
                continue
            resolution.status = "granted"
            resolution.delivery_target = "inventory"
            resolution.quantity_granted = quantity
            resolution.inventory_grants = [
                {"slot_id": row.slot_id, "quantity": row.quantity} for row in rows
            ]
            delivered.extend(rows)
        return delivered, resolutions

    def _resolve_durability(
        self, definition: ItemDefinition, requested: int | None
    ) -> int | None:
        if definition.max_durability is None:
            if requested is not None:
                raise ValueError(f"{definition.title} is indestructible")
            return None
        durability = definition.max_durability if requested is None else int(requested)
        if durability < 0 or durability > definition.max_durability:
            raise ValueError(
                f"Durability must be between 0 and {definition.max_durability}"
            )
        return durability

    def _resolve_charges(self, definition: ItemDefinition, requested: int | None) -> int | None:
        if definition.max_charges is None:
            if requested is not None:
                raise ValueError(f"{definition.title} has no charges")
            return None
        charges = definition.max_charges if requested is None else int(requested)
        if charges < 0 or charges > definition.max_charges:
            raise ValueError(f"Charges must be between 0 and {definition.max_charges}")
        return charges

    def _lock_user(self, user_id: int) -> UserProgress:
        user = (
            self.db.query(UserProgress)
            .filter(UserProgress.id == user_id)
            .with_for_update(of=UserProgress)
            .first()
        )
        if not user:
            raise ValueError("User not found")
        return user

    def _lock_items(self, user_id: int) -> list[InventoryItem]:
        return (
            self.db.query(InventoryItem)
            .filter(InventoryItem.user_id == user_id)
            .order_by(InventoryItem.slot_id.asc())
            .with_for_update(of=InventoryItem)
            .all()
        )

    def _max_slots(self, user: UserProgress) -> int:
        base_slots = int(getattr(user, "base_inventory_slots", None) or 20)
        return max(base_slots + self.max_slots_add, 1)
