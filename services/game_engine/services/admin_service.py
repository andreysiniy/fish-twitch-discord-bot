from typing import List
from infrastructure.repositories.channel_repo import ChannelRepository
from infrastructure.repositories.user_repo import UserRepository
from domain.schemas.admin import ChannelCreateDTO, ChannelUpdateDTO, PlayerListResponse

class AdminService:
    def __init__(self, channel_repo: ChannelRepository, user_repo: UserRepository):
        self.repo = channel_repo
        self.user_repo = user_repo

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