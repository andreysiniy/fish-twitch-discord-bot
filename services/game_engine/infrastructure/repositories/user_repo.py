from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import func
import random
from infrastructure.models import UserProgress, Channel, ItemDefinition, InventoryItem

class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_progress(self, user_twitch_id: str, channel_twitch_id: str) -> UserProgress | None:
        channel = self.db.query(Channel).filter(Channel.twitch_id == channel_twitch_id).first()
        
        if not channel:
            return None

        return self.db.query(UserProgress).filter(
            UserProgress.user_twitch_id == user_twitch_id,
            UserProgress.channel_id == channel.id
        ).first()

    def create(self, user_twitch_id: str, username: str, channel_twitch_id: str) -> UserProgress:
        channel = self.db.query(Channel).filter(Channel.twitch_id == channel_twitch_id).first()
        if not channel:
            channel = Channel(twitch_id=channel_twitch_id, name="Unknown_Channel")
            self.db.add(channel)
            self.db.commit()
            self.db.refresh(channel)

        user = UserProgress(
            user_twitch_id=user_twitch_id,
            username=username,
            channel_id=channel.id,
            inventory={"equipped_rod_slot": None, "max_slots": 20}
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_users_by_channel(self, channel_twitch_id: str, skip: int = 0, limit: int = 50) -> tuple[list[UserProgress], int]:
        channel = self.db.query(Channel).filter(Channel.twitch_id == channel_twitch_id).first()
        if not channel:
            return [], 0

        query = self.db.query(UserProgress).filter(UserProgress.channel_id == channel.id)

        total = query.count()

        users = query.order_by(UserProgress.level.desc(), UserProgress.xp.desc())\
                     .offset(skip).limit(limit).all()

        return users, total
    
    def get_random_victim(self, channel_id: int, exclude_user_id: int) -> UserProgress | None:
        return self.db.query(UserProgress).filter(
            UserProgress.channel_id == channel_id,
            UserProgress.id != exclude_user_id,
            UserProgress.current_mass > 0
        ).order_by(func.random()).first()
    
    def get_rich_victim(self, channel_id: int, attacker_id: int, lookup_range: int = 5) -> UserProgress | None:
        attacker = self.db.query(UserProgress).filter(UserProgress.id == attacker_id).first()
        if not attacker:
            return None
        attacker_mass = attacker.current_mass
        candidates = (self.db.query(UserProgress)
            .filter(
                UserProgress.channel_id == channel_id,
                UserProgress.id != attacker_id,
                UserProgress.current_mass >= attacker_mass,
                UserProgress.current_mass > 0
            )
            .order_by(UserProgress.current_mass.asc())
            .limit(lookup_range)
            .all()
        )
        if not candidates:
            return self.get_random_victim(channel_id, attacker_id)
        return random.choice(candidates)        

    def update_inventory(self, user: UserProgress, item_data: dict):
        item_id = str(item_data.get("item_id", "")).strip()
        if not item_id:
            raise ValueError("item_id is required for inventory update")

        definition = self.db.query(ItemDefinition).filter(ItemDefinition.id == item_id).first()
        if not definition:
            definition = ItemDefinition(
                id=item_id,
                name=item_data.get("name", item_id),
                description=item_data.get("description"),
                type=item_data.get("type", "fish"),
                rarity=item_data.get("rarity", "common"),
                image_url=item_data.get("image_url"),
                base_stats=item_data.get("stats", {}) or {}
            )
            self.db.add(definition)
            self.db.flush()

        next_slot_id = self._get_next_slot_id(user.id)
        quantity = max(int(item_data.get("quantity", 1) or 1), 1)
        meta = {"obtained_at": item_data.get("obtained_at")} if item_data.get("obtained_at") else {}

        inv_item = InventoryItem(
            user_id=user.id,
            item_id=item_id,
            slot_id=next_slot_id,
            quantity=quantity,
            current_durability=item_data.get("current_durability"),
            meta=meta
        )
        self.db.add(inv_item)
        self.db.commit()
        self.db.refresh(inv_item)
        return inv_item

    def grant_item_to_user(
        self,
        user: UserProgress,
        item_id: str,
        quantity: int = 1,
        slot_id: int | None = None,
        current_durability: int | None = None,
        meta: dict | None = None
    ) -> InventoryItem:
        definition = self.db.query(ItemDefinition).filter(ItemDefinition.id == item_id).first()
        if not definition:
            raise ValueError(f"Item definition '{item_id}' not found")

        final_slot_id = slot_id if slot_id is not None else self._get_next_slot_id(user.id)
        if slot_id is not None:
            occupied = (
                self.db.query(InventoryItem)
                .filter(InventoryItem.user_id == user.id, InventoryItem.slot_id == slot_id)
                .first()
            )
            if occupied:
                raise ValueError(f"Slot {slot_id} is already occupied")

        inv_item = InventoryItem(
            user_id=user.id,
            item_id=item_id,
            slot_id=final_slot_id,
            quantity=max(int(quantity or 1), 1),
            current_durability=current_durability,
            meta=meta or {}
        )
        self.db.add(inv_item)
        self.db.commit()
        self.db.refresh(inv_item)
        return inv_item

    def get_user_inventory_items(self, user_id: int) -> list[InventoryItem]:
        return (
            self.db.query(InventoryItem)
            .filter(InventoryItem.user_id == user_id)
            .order_by(InventoryItem.slot_id.asc())
            .all()
        )

    def _get_next_slot_id(self, user_id: int) -> int:
        max_slot = (
            self.db.query(func.max(InventoryItem.slot_id))
            .filter(InventoryItem.user_id == user_id)
            .scalar()
        )
        return int(max_slot or 0) + 1

    def save_progress(self, user: UserProgress):
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
