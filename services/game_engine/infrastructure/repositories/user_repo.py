from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql.expression import func
import random
from infrastructure.models import UserProgress, Channel

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
            inventory={"items": [], "equipped_rod": None} 
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
        if not user.inventory:
            user.inventory = {"items": [], "equipped_rod": None}

        if "items" not in user.inventory:
            user.inventory["items"] = []
        current_items = user.inventory["items"]
        if current_items:
            max_slot_id = max(item.get("slot_id", 0) for item in current_items)
            next_slot_id = max_slot_id + 1
        else:
            next_slot_id = 1
        item_data["slot_id"] = next_slot_id

        user.inventory["items"].append(item_data)

        flag_modified(user, "inventory")
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

    def save_progress(self, user: UserProgress):
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)