from typing import List
from infrastructure.repositories.channel_repo import ChannelRepository
from infrastructure.repositories.config_repo import ConfigRepository
from infrastructure.repositories.user_repo import UserRepository
from domain.schemas.admin import (
    ALLOWED_CHANNEL_ROLES,
    ChannelAccessResponseDTO,
    ChannelAccessUpsertDTO,
    ChannelCreateDTO,
    ChannelUpdateDTO,
    PlayerListResponse,
    RewardPoolUpdateDTO,
)

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

    def check_access(
        self,
        channel_twitch_id: str,
        requester_twitch_id: str,
        owner_only: bool = False
    ):
        channel = self.repo.get_by_twitch_id(channel_twitch_id)
        if not channel:
            raise ValueError("Channel not found")

        is_owner = channel.twitch_id == requester_twitch_id
        if is_owner:
            return channel

        if owner_only:
            raise PermissionError("Only the channel owner can perform this action")

        access = self.repo.get_access_record(channel.id, requester_twitch_id)
        if access and access.role in ALLOWED_CHANNEL_ROLES:
            return channel

        raise PermissionError("Access denied for this channel")

    def get_players(
        self,
        requester_twitch_id: str,
        channel_twitch_id: str,
        skip: int,
        limit: int
    ) -> PlayerListResponse:
        self.check_access(channel_twitch_id, requester_twitch_id)
        users, total = self.user_repo.get_users_by_channel(channel_twitch_id, skip, limit)
        return PlayerListResponse(total=total, players=users)

    def update_channel_rewards(
        self,
        requester_twitch_id: str,
        twitch_id: str,
        location_id: str,
        data: RewardPoolUpdateDTO
    ):
        channel = self.check_access(twitch_id, requester_twitch_id)
        
        return self.repo.update_rewards(
            channel.id,
            location_id,
            data.rewards,
            data.items or [],
            data.items_drop_rate,
            data.requirements,
            data.location_name
        )

    def get_channel_rewards(self, requester_twitch_id: str, twitch_id: str, location_id: str):
        channel = self.check_access(twitch_id, requester_twitch_id)
        
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

    def list_channel_access(self, requester_twitch_id: str, channel_twitch_id: str) -> list[ChannelAccessResponseDTO]:
        channel = self.check_access(channel_twitch_id, requester_twitch_id, owner_only=True)
        return [
            ChannelAccessResponseDTO.model_validate(record)
            for record in self.repo.list_access_records(channel.id)
        ]

    def upsert_channel_access(
        self,
        requester_twitch_id: str,
        channel_twitch_id: str,
        data: ChannelAccessUpsertDTO
    ) -> ChannelAccessResponseDTO:
        channel = self.check_access(channel_twitch_id, requester_twitch_id, owner_only=True)

        role = data.role.strip().lower()
        if role not in ALLOWED_CHANNEL_ROLES:
            raise ValueError(f"Unsupported role. Allowed values: {', '.join(sorted(ALLOWED_CHANNEL_ROLES))}")

        if data.user_twitch_id == channel.twitch_id:
            raise ValueError("Channel owner role is managed by channel ownership")

        record = self.repo.upsert_access_record(channel.id, data.user_twitch_id, role)
        return ChannelAccessResponseDTO.model_validate(record)

    def remove_channel_access(self, requester_twitch_id: str, channel_twitch_id: str, user_twitch_id: str) -> None:
        channel = self.check_access(channel_twitch_id, requester_twitch_id, owner_only=True)

        if user_twitch_id == channel.twitch_id:
            raise ValueError("Channel owner role cannot be removed")

        removed = self.repo.delete_access_record(channel.id, user_twitch_id)
        if not removed:
            raise ValueError("Channel access record not found")
