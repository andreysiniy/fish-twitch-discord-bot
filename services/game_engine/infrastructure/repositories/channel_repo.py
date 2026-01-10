from sqlalchemy.orm import Session
from infrastructure.models import Channel, RewardPool
from domain.schemas.admin import ChannelCreateDTO, ChannelUpdateDTO

class ChannelRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_all(self, skip: int = 0, limit: int = 100) -> list[Channel]:
        return self.db.query(Channel).offset(skip).limit(limit).all()

    def get_by_twitch_id(self, twitch_id: str) -> Channel | None:
        return self.db.query(Channel).filter(Channel.twitch_id == twitch_id).first()

    def create(self, data: ChannelCreateDTO) -> Channel:
        channel = Channel(
            twitch_id=data.twitch_id, 
            name=data.name,
            config={"prefix": "!"} 
        )
        self.db.add(channel)
        self.db.commit()
        self.db.refresh(channel)
        return channel

    def update(self, channel_id: int, data: ChannelUpdateDTO) -> Channel | None:
        channel = self.db.query(Channel).filter(Channel.id == channel_id).first()
        if not channel:
            return None
        
        if data.is_active is not None:
            channel.is_active = data.is_active
        if data.config is not None:
            channel.config = data.config
            
        self.db.commit()
        self.db.refresh(channel)
        return channel


    def update_rewards(self, channel_id: int, location_id: str, rewards: list) -> RewardPool:
        pool = self.db.query(RewardPool).filter(
            RewardPool.channel_id == channel_id,
            RewardPool.location_id == location_id
        ).first()

        if pool:
            pool.rewards_data = rewards
        else:
            pool = RewardPool(
                channel_id=channel_id,
                location_id=location_id,
                rewards_data=rewards
            )
            self.db.add(pool)
        
        self.db.commit()
        self.db.refresh(pool)
        return pool
    
    def get_rewards(self, channel_id: int, location_id: str) -> RewardPool | None:
        return self.db.query(RewardPool).filter(
            RewardPool.channel_id == channel_id, 
            RewardPool.location_id == location_id
        ).first()