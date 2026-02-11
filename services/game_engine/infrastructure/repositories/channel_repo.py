from sqlalchemy.orm import Session
from infrastructure.models import Channel, RewardPool, LocationItem
from domain.schemas.admin import ChannelCreateDTO, ChannelUpdateDTO
from domain.schemas.rpg import DropItemDTO

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


    def _fallback_location_name(self, location_id: str) -> str:
        raw = (location_id or "default").strip()
        if not raw:
            return "Default"
        return raw.replace("_", " ").replace("-", " ").title()

    def update_rewards(
        self,
        channel_id: int,
        location_id: str,
        rewards: list,
        items: list[DropItemDTO],
        items_drop_rate: float,
        requirements: dict | None = None,
        location_name: str | None = None
    ) -> RewardPool:
        pool = self.db.query(RewardPool).filter(
            RewardPool.channel_id == channel_id,
            RewardPool.location_id == location_id
        ).first()

        if not pool:
            pool = RewardPool(
                channel_id=channel_id,
                location_id=location_id,
                location_name=location_name or self._fallback_location_name(location_id)
            )
            self.db.add(pool)
            self.db.commit()
            self.db.refresh(pool)
        
        pool.rewards_data = rewards
        pool.items_drop_rate = items_drop_rate
        if location_name is not None:
            pool.location_name = location_name
        elif not pool.location_name:
            pool.location_name = self._fallback_location_name(location_id)
        if requirements is not None:
            pool.requirements = requirements

        self.db.query(LocationItem).filter(LocationItem.reward_pool_id == pool.id).delete()
        for item_dto in items:
            db_item = LocationItem(
                reward_pool_id=pool.id,
                name=item_dto.name,
                item_id=item_dto.item_id,
                description=item_dto.description,
                image_url=item_dto.image_url,
                type=item_dto.type,
                
                weight=item_dto.weight,
                rarity=item_dto.rarity.value, 
                xp_gain=item_dto.xp_gain,
                quantity=item_dto.quantity,
                message=item_dto.message,
                
                item_stats=item_dto.stats.model_dump()
            )
            self.db.add(db_item)

        
        self.db.commit()
        self.db.refresh(pool)
        return pool
    
    def get_rewards(self, channel_id: int, location_id: str) -> RewardPool | None:
        return self.db.query(RewardPool).filter(
            RewardPool.channel_id == channel_id, 
            RewardPool.location_id == location_id
        ).first()
