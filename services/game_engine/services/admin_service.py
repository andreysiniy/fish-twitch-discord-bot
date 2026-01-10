from typing import List
from infrastructure.repositories.channel_repo import ChannelRepository
from domain.schemas.admin import ChannelCreateDTO, ChannelUpdateDTO

class AdminService:
    def __init__(self, channel_repo: ChannelRepository):
        self.repo = channel_repo

    def create_channel(self, data: ChannelCreateDTO):
        existing = self.repo.get_by_twitch_id(data.twitch_id)
        if existing:
            raise ValueError(f"Channel {data.name} already exists")
        return self.repo.create(data)

    def get_channels(self) -> List:
        return self.repo.get_all()

    def update_channel_rewards(self, twitch_id: str, location_id: str, rewards: list):
        channel = self.repo.get_by_twitch_id(twitch_id)
        if not channel:
            raise ValueError("Channel not found")
        
        return self.repo.update_rewards(channel.id, location_id, rewards)

    def get_channel_rewards(self, twitch_id: str, location_id: str):
        channel = self.repo.get_by_twitch_id(twitch_id)
        if not channel:
            raise ValueError(f"Channel {twitch_id} not found")
        
        pool = self.repo.get_rewards(channel.id, location_id)
        
        if not pool:
            return {
                "location_id": location_id,
                "rewards_data": []
            }
            
        return pool