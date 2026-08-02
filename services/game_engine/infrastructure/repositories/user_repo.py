from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import func
import random

from infrastructure.models import UserProgress, Channel, InventoryItem
from infrastructure.repositories.inventory_repo import InventoryRepository


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_channel(self, channel_twitch_id: str) -> Channel | None:
        return self.db.query(Channel).filter(Channel.twitch_id == channel_twitch_id).first()

    def get_progress(self, user_twitch_id: str, channel_twitch_id: str) -> UserProgress | None:
        channel = self.get_channel(channel_twitch_id)

        if not channel:
            return None

        return self.db.query(UserProgress).filter(
            UserProgress.user_twitch_id == user_twitch_id,
            UserProgress.channel_id == channel.id,
        ).first()

    def create(self, user_twitch_id: str, username: str, channel_twitch_id: str) -> UserProgress:
        channel = self.db.query(Channel).filter(Channel.twitch_id == channel_twitch_id).first()
        if not channel:
            channel = Channel(twitch_id=channel_twitch_id, name="Unknown_Channel")
            self.db.add(channel)
            self.db.flush()
            self.db.refresh(channel)

        user = UserProgress(
            user_twitch_id=user_twitch_id,
            username=username,
            channel_id=channel.id,
            inventory={"equipped_rod_slot": None, "max_slots": 20},
        )
        self.db.add(user)
        self.db.flush()
        self.db.refresh(user)
        return user

    def get_users_by_channel(
        self,
        channel_twitch_id: str,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[UserProgress], int]:
        channel = self.db.query(Channel).filter(Channel.twitch_id == channel_twitch_id).first()
        if not channel:
            return [], 0

        query = self.db.query(UserProgress).filter(UserProgress.channel_id == channel.id)

        total = query.count()

        users = query.order_by(UserProgress.level.desc(), UserProgress.xp.desc()).offset(skip).limit(limit).all()

        return users, total

    def get_user_rank(self, channel_id: int, user_id: int) -> int:
        user = self.db.query(UserProgress).filter(UserProgress.id == user_id).first()
        if not user:
            return 0

        higher_count = (
            self.db.query(UserProgress)
            .filter(
                UserProgress.channel_id == channel_id,
                UserProgress.current_mass > user.current_mass,
            )
            .count()
        )
        return higher_count + 1

    def get_top_users_by_channel(
        self,
        channel_twitch_id: str,
        limit: int = 10,
        mode: str = "current",
    ) -> list[UserProgress]:
        channel = self.db.query(Channel).filter(Channel.twitch_id == channel_twitch_id).first()
        if not channel:
            return []

        mode = (mode or "current").lower()
        query = self.db.query(UserProgress).filter(UserProgress.channel_id == channel.id)

        if mode == "alltime":
            query = query.order_by(UserProgress.total_mass_stat.desc(), UserProgress.id.asc())
        elif mode == "catches":
            query = query.order_by(UserProgress.total_fish_stat.desc(), UserProgress.id.asc())
        elif mode == "level":
            query = query.order_by(UserProgress.level.desc(), UserProgress.xp.desc(), UserProgress.id.asc())
        else:
            query = query.order_by(UserProgress.current_mass.desc(), UserProgress.id.asc())

        return query.limit(limit).all()

    def get_random_victim(self, channel_id: int, exclude_user_id: int) -> UserProgress | None:
        return self.db.query(UserProgress).filter(
            UserProgress.channel_id == channel_id,
            UserProgress.id != exclude_user_id,
            UserProgress.current_mass > 0,
        ).order_by(func.random()).first()

    def get_rich_victim(
        self,
        channel_id: int,
        attacker_id: int,
        lookup_range: int = 5,
    ) -> UserProgress | None:
        attacker = self.db.query(UserProgress).filter(UserProgress.id == attacker_id).first()
        if not attacker:
            return None
        attacker_mass = attacker.current_mass
        candidates = (
            self.db.query(UserProgress)
            .filter(
                UserProgress.channel_id == channel_id,
                UserProgress.id != attacker_id,
                UserProgress.current_mass >= attacker_mass,
                UserProgress.current_mass > 0,
            )
            .order_by(UserProgress.current_mass.asc())
            .limit(lookup_range)
            .all()
        )
        if not candidates:
            return self.get_random_victim(channel_id, attacker_id)
        return random.choice(candidates)

    def lock_users(self, user_ids: list[int]) -> dict[int, UserProgress]:
        normalized_ids = sorted({int(user_id) for user_id in user_ids})
        rows = (
            self.db.query(UserProgress)
            .filter(UserProgress.id.in_(normalized_ids))
            .order_by(UserProgress.id.asc())
            .with_for_update(of=UserProgress)
            .populate_existing()
            .all()
        )
        if len(rows) != len(normalized_ids):
            raise ValueError("User not found while locking robbery participants")
        return {row.id: row for row in rows}

    def update_inventory(self, user: UserProgress, item_data: dict):
        item_id = str(item_data.get("item_id", "")).strip()
        if not item_id:
            raise ValueError("item_id is required for inventory update")
        meta = dict(item_data.get("meta") or {})
        if item_data.get("obtained_at"):
            meta["obtained_at"] = item_data["obtained_at"]
        granted = InventoryRepository(self.db).grant_many(
            user,
            [
                {
                    "item_id": item_id,
                    "quantity": item_data.get("quantity", 1),
                    "current_durability": item_data.get("current_durability"),
                    "meta": meta,
                }
            ],
        )
        return granted[0]

    def grant_item_to_user(
        self,
        user: UserProgress,
        item_id: str,
        quantity: int = 1,
        slot_id: int | None = None,
        current_durability: int | None = None,
        meta: dict | None = None,
    ) -> InventoryItem:
        granted = InventoryRepository(self.db).grant_many(
            user,
            [
                {
                    "item_id": item_id,
                    "quantity": quantity,
                    "slot_id": slot_id,
                    "current_durability": current_durability,
                    "meta": meta or {},
                }
            ],
        )
        return granted[0]

    def get_user_inventory_items(self, user_id: int) -> list[InventoryItem]:
        return (
            self.db.query(InventoryItem)
            .filter(InventoryItem.user_id == user_id)
            .order_by(InventoryItem.slot_id.asc())
            .all()
        )

    def apply_equipped_rod_durability_loss(
        self,
        user: UserProgress,
        durability_loss: int,
    ) -> str | None:
        return InventoryRepository(self.db).consume_durability(
            user.id, "rod", durability_loss
        )

    def _get_next_slot_id(self, user_id: int) -> int:
        occupied = {
            row[0]
            for row in self.db.query(InventoryItem.slot_id)
            .filter(InventoryItem.user_id == user_id)
            .all()
        }
        slot_id = 1
        while slot_id in occupied:
            slot_id += 1
        return slot_id

    def save_progress(self, user: UserProgress):
        self.db.add(user)
        self.db.flush()
        self.db.refresh(user)
