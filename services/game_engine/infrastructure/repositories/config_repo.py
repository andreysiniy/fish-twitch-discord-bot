from sqlalchemy.orm import Session
from infrastructure.models import RewardPool, Channel
from infrastructure.repositories.base import BaseRepository

class ConfigRepository(BaseRepository[RewardPool]):
    def __init__(self, db: Session):
        super().__init__(db, RewardPool)

    def get_pool(self, channel_twitch_id: str, location_id: str) -> list[dict]: 
        pool = (self.db.query(RewardPool)
                .join(Channel)
                .filter(Channel.twitch_id == channel_twitch_id)
                .filter(RewardPool.location_id == location_id)
                .first())
        
        if pool:
            return pool.rewards_data
        
        return [{"type": "nothing", "weight": 100, "message": "No fish here..."}]