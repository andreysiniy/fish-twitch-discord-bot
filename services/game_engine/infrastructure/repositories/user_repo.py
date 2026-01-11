from sqlalchemy.orm import Session
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

    def update_inventory(self, user: UserProgress, item_name: str):
        current_inv = dict(user.inventory)
        
        if "items" not in current_inv:
            current_inv["items"] = []
            
        current_inv["items"].append(item_name)
        
        user.inventory = current_inv
        self.db.commit()
        self.db.refresh(user)

    def save_progress(self, user: UserProgress):
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)