from sqlalchemy.orm import Session
from infrastructure.models import RewardPool, Channel, LocationItem
from sqlalchemy import or_
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

    def get_locations(self, channel_twitch_id: str) -> list[RewardPool]:
        return (
            self.db.query(RewardPool)
            .join(Channel)
            .filter(Channel.twitch_id == channel_twitch_id)
            .order_by(RewardPool.location_id.asc())
            .all()
        )
    
    def get_dual_pool(self, channel_twitch_id: str, location_id: str):
        """
        Returns:
        1. Rewards list (from JSON)
        2. Items list (from DB)
        3. Item drop rate (float)
        """
        pool_obj = (self.db.query(RewardPool)
                .join(Channel)
                .filter(Channel.twitch_id == channel_twitch_id)
                .filter(RewardPool.location_id == location_id)
                .first())
        
        if not pool_obj:
            return [{"type": "nothing", "weight": 100, "base_message": "No fish here..."}], [], 0.0

        rewards = list(pool_obj.rewards_data)
        if not rewards:
            rewards = [{"type": "nothing", "weight": 100, "base_message": "No fish here..."}]

        db_items = self.db.query(LocationItem).filter(
            LocationItem.reward_pool_id == pool_obj.id,
            or_(LocationItem.quantity == None, LocationItem.quantity > 0)
        ).all()
        
        items = []
        for item in db_items:
            
            items.append({
                "type": "item",
                "db_id": item.id,
                "item_id": item.item_id,
                "name": item.name,
                "weight": item.weight,
                "rarity": item.rarity,
                "xp_gain": item.xp_gain,
                "message": item.message,
                "stats": item.item_stats
            })

        return rewards, items, pool_obj.items_drop_rate
