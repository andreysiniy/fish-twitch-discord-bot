from typing import List
from infrastructure.repositories.channel_repo import ChannelRepository
from infrastructure.repositories.config_repo import ConfigRepository
from infrastructure.repositories.user_repo import UserRepository
from domain.schemas.admin import ChannelCreateDTO, ChannelUpdateDTO, PlayerListResponse, RewardPoolUpdateDTO

class AdminService:
    def __init__(self, channel_repo: ChannelRepository, user_repo: UserRepository, config_repo: ConfigRepository):
        self.repo = channel_repo
        self.user_repo = user_repo
        self.config_repo = config_repo

    def create_channel(self, data: ChannelCreateDTO):
        existing = self.repo.get_by_twitch_id(data.twitch_id)
        if existing:
            raise ValueError(f"Channel {data.name} already exists")
        return self.repo.create(data)

    def get_channels(self) -> List:
        return self.repo.get_all()
    
    def get_players(self, channel_twitch_id: str, skip: int, limit: int) -> PlayerListResponse:
        users, total = self.user_repo.get_users_by_channel(channel_twitch_id, skip, limit)
        return PlayerListResponse(total=total, players=users)

    def update_channel_rewards(self, twitch_id: str, location_id: str, data: RewardPoolUpdateDTO):
        channel = self.repo.get_by_twitch_id(twitch_id)
        if not channel:
            raise ValueError("Channel not found")
        
        return self.repo.update_rewards(
            channel.id,
            location_id,
            data.rewards,
            data.items or [],
            data.items_drop_rate,
            data.requirements,
            data.location_name
        )

    def get_channel_rewards(self, twitch_id: str, location_id: str):
        channel = self.repo.get_by_twitch_id(twitch_id)
        if not channel:
            raise ValueError(f"Channel {twitch_id} not found")
        
        rewards = {}
        loot_pool, item_pool, items_drop_rate = self.config_repo.get_dual_pool(twitch_id, location_id)
        pool = self.repo.get_rewards(channel.id, location_id)
        requirements = pool.requirements if pool and isinstance(pool.requirements, dict) else {}
        location_name = (
            pool.location_name
            if pool and isinstance(pool.location_name, str) and pool.location_name.strip()
            else location_id
        )
        
        if not loot_pool:
            rewards = {
                "location_id": location_id,
                "location_name": location_name,
                "requirements": requirements,
                "items_drop_rate": 0,
                "rewards_data": [],
                "items": []
            }
            
        rewards.update({
            "location_id": location_id,
            "location_name": location_name,
            "requirements": requirements,
            "items_drop_rate": items_drop_rate,
            "rewards_data": loot_pool,
            "items": item_pool
        })

        return rewards
