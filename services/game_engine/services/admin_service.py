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
    ItemDefinitionCreateDTO,
    GrantItemRequestDTO,
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
        username = data.user_twitch_name.strip()
        if not username:
            raise ValueError("user_twitch_name is required")

        if data.user_twitch_id == channel.twitch_id:
            raise ValueError("Channel owner role is managed by channel ownership")

        record = self.repo.upsert_access_record(
            channel.id,
            data.user_twitch_id,
            username,
            role
        )
        return ChannelAccessResponseDTO.model_validate(record)

    def remove_channel_access(self, requester_twitch_id: str, channel_twitch_id: str, user_twitch_id: str) -> None:
        channel = self.check_access(channel_twitch_id, requester_twitch_id, owner_only=True)

        if user_twitch_id == channel.twitch_id:
            raise ValueError("Channel owner role cannot be removed")

        removed = self.repo.delete_access_record(channel.id, user_twitch_id)
        if not removed:
            raise ValueError("Channel access record not found")

    def upsert_item_definition(self, data: ItemDefinitionCreateDTO):
        item_id = data.item_id.strip()
        if not item_id:
            raise ValueError("item_id is required")
        return self.repo.upsert_item_definition(
            item_id=item_id,
            name=data.name,
            description=data.description,
            item_type=data.type,
            rarity=data.rarity,
            image_url=data.image_url,
            base_stats=data.base_stats,
            is_sellable=data.is_sellable,
            is_tradeable=data.is_tradeable
        )

    def list_item_definitions(self, skip: int = 0, limit: int = 200):
        return self.repo.list_item_definitions(skip=skip, limit=limit)

    def grant_item_to_player(self, requester_twitch_id: str, data: GrantItemRequestDTO):
        self.check_access(data.channel_twitch_id, requester_twitch_id)
        user = self.user_repo.get_progress(data.user_twitch_id, data.channel_twitch_id)
        if not user:
            raise ValueError("Player not found")

        inv_item = self.user_repo.grant_item_to_user(
            user=user,
            item_id=data.item_id,
            quantity=data.quantity,
            slot_id=data.slot_id,
            current_durability=data.current_durability,
            meta=data.meta
        )
        return inv_item

    def get_player_inventory(self, requester_twitch_id: str, channel_twitch_id: str, user_twitch_id: str):
        self.check_access(channel_twitch_id, requester_twitch_id)
        user = self.user_repo.get_progress(user_twitch_id, channel_twitch_id)
        if not user:
            raise ValueError("Player not found")

        inventory_meta = dict(user.inventory or {})
        items = [self._serialize_inventory_item(item) for item in self.user_repo.get_user_inventory_items(user.id)]
        return {
            "items": items,
            "equipped_rod_slot": inventory_meta.get("equipped_rod_slot"),
            "max_slots": inventory_meta.get("max_slots", 20)
        }

    def _serialize_inventory_item(self, item):
        definition = item.definition
        return {
            "item_id": item.item_id,
            "name": definition.name if definition else item.item_id,
            "description": definition.description if definition else None,
            "rarity": definition.rarity if definition else "common",
            "type": definition.type if definition else "fish",
            "image_url": definition.image_url if definition else None,
            "stats": definition.base_stats if definition else {},
            "quantity": item.quantity,
            "slot_id": item.slot_id,
            "current_durability": item.current_durability,
            "obtained_at": (item.meta or {}).get("obtained_at")
        }
