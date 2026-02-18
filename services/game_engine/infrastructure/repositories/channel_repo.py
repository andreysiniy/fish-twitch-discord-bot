from sqlalchemy.orm import Session
from infrastructure.models import Channel, RewardPool, LocationItem, ChannelAccessRole, ItemDefinition, FishingEvent
from domain.schemas.admin import ChannelCreateDTO, ChannelUpdateDTO, LocationItemUpdateDTO

UNSET = object()


class ChannelRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def get_all(self, skip: int = 0, limit: int = 100) -> list[Channel]:
        return self.db.query(Channel).offset(skip).limit(limit).all()

    def get_by_twitch_id(self, twitch_id: str) -> Channel | None:
        return self.db.query(Channel).filter(Channel.twitch_id == twitch_id).first()

    def get_access_record(self, channel_id: int, user_twitch_id: str) -> ChannelAccessRole | None:
        return self.db.query(ChannelAccessRole).filter(
            ChannelAccessRole.channel_id == channel_id,
            ChannelAccessRole.user_twitch_id == user_twitch_id
        ).first()

    def upsert_access_record(
        self,
        channel_id: int,
        user_twitch_id: str,
        user_twitch_name: str,
        role: str
    ) -> ChannelAccessRole:
        record = self.get_access_record(channel_id, user_twitch_id)
        if record:
            record.user_twitch_name = user_twitch_name
            record.role = role
        else:
            record = ChannelAccessRole(
                channel_id=channel_id,
                user_twitch_id=user_twitch_id,
                user_twitch_name=user_twitch_name,
                role=role
            )
            self.db.add(record)

        self.db.commit()
        self.db.refresh(record)
        return record

    def delete_access_record(self, channel_id: int, user_twitch_id: str) -> bool:
        record = self.get_access_record(channel_id, user_twitch_id)
        if not record:
            return False
        self.db.delete(record)
        self.db.commit()
        return True

    def list_access_records(self, channel_id: int) -> list[ChannelAccessRole]:
        return self.db.query(ChannelAccessRole).filter(
            ChannelAccessRole.channel_id == channel_id
        ).all()

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
        items: list[LocationItemUpdateDTO],
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
            item_id = item_dto.item_id.strip()
            if not item_id:
                continue

            definition = self.db.query(ItemDefinition).filter(ItemDefinition.id == item_id).first()
            if not definition:
                raise ValueError(f"ItemDefinition '{item_id}' not found")

            db_item = LocationItem(
                reward_pool_id=pool.id,
                item_id=item_id,
                weight=item_dto.weight,
                xp_gain=item_dto.xp_gain,
                quantity=item_dto.quantity,
                message=item_dto.message,
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

    def upsert_item_definition(
        self,
        item_id: str,
        name: str,
        description: str | None = None,
        item_type: str = "fish",
        rarity: str = "common",
        image_url: str | None = None,
        base_stats: dict | None = None,
        is_sellable: bool = True,
        is_tradeable: bool = True
    ) -> ItemDefinition:
        definition = self.db.query(ItemDefinition).filter(ItemDefinition.id == item_id).first()
        if not definition:
            definition = ItemDefinition(id=item_id)
            self.db.add(definition)

        definition.name = name
        definition.description = description
        definition.type = item_type
        definition.rarity = rarity
        definition.image_url = image_url
        definition.base_stats = base_stats or {}
        definition.is_sellable = is_sellable
        definition.is_tradeable = is_tradeable
        self.db.commit()
        self.db.refresh(definition)
        return definition

    def get_item_definition(self, item_id: str) -> ItemDefinition | None:
        return self.db.query(ItemDefinition).filter(ItemDefinition.id == item_id).first()

    def list_item_definitions(self, skip: int = 0, limit: int = 200) -> list[ItemDefinition]:
        return (
            self.db.query(ItemDefinition)
            .order_by(ItemDefinition.id.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_active_fishing_event(self, channel_id: int) -> FishingEvent | None:
        return (
            self.db.query(FishingEvent)
            .filter(FishingEvent.channel_id == channel_id, FishingEvent.is_active.is_(True))
            .order_by(FishingEvent.id.desc())
            .first()
        )

    def list_fishing_events(self, channel_id: int) -> list[FishingEvent]:
        return (
            self.db.query(FishingEvent)
            .filter(FishingEvent.channel_id == channel_id)
            .order_by(FishingEvent.id.asc())
            .all()
        )

    def get_fishing_event(self, channel_id: int, event_id: int) -> FishingEvent | None:
        return (
            self.db.query(FishingEvent)
            .filter(FishingEvent.channel_id == channel_id, FishingEvent.id == event_id)
            .first()
        )

    def create_fishing_event(
        self,
        channel_id: int,
        event_title: str,
        modifiers: dict | None = None,
        override_loot_pool: str | None = None,
        is_active: bool = False
    ) -> FishingEvent:
        self._validate_override_loot_pool(channel_id, override_loot_pool)
        event = FishingEvent(
            channel_id=channel_id,
            event_title=event_title,
            modifiers=modifiers or {},
            override_loot_pool=str(override_loot_pool).strip() if override_loot_pool is not None else None,
            is_active=False
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        if is_active:
            event = self.set_active_fishing_event(channel_id, event.id)
        return event

    def update_fishing_event(
        self,
        channel_id: int,
        event_id: int,
        event_title: str | None = None,
        modifiers: dict | None = None,
        override_loot_pool: str | None | object = UNSET,
        is_active: bool | None = None
    ) -> FishingEvent | None:
        event = self.get_fishing_event(channel_id, event_id)
        if not event:
            return None

        if override_loot_pool is not UNSET:
            self._validate_override_loot_pool(channel_id, override_loot_pool)

        if event_title is not None:
            event.event_title = event_title
        if modifiers is not None:
            event.modifiers = modifiers
        if override_loot_pool is not UNSET:
            event.override_loot_pool = str(override_loot_pool).strip() if override_loot_pool is not None else None

        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)

        if is_active is True:
            event = self.set_active_fishing_event(channel_id, event.id)
        elif is_active is False and event.is_active:
            event = self.set_active_fishing_event(channel_id, None)
        return event

    def delete_fishing_event(self, channel_id: int, event_id: int) -> bool:
        event = self.get_fishing_event(channel_id, event_id)
        if not event:
            return False
        self.db.delete(event)
        self.db.commit()
        return True

    def set_active_fishing_event(self, channel_id: int, event_id: int | None) -> FishingEvent | None:
        events = self.list_fishing_events(channel_id)
        target: FishingEvent | None = None
        for event in events:
            should_be_active = event_id is not None and event.id == event_id
            event.is_active = bool(should_be_active)
            if should_be_active:
                target = event

        self.db.commit()
        if target:
            self.db.refresh(target)
        return target

    def _validate_override_loot_pool(self, channel_id: int, override_loot_pool: str | None) -> None:
        if override_loot_pool is None:
            return

        normalized_location_id = str(override_loot_pool).strip()
        if not normalized_location_id:
            raise ValueError("override_loot_pool location_id cannot be empty")

        pool = (
            self.db.query(RewardPool)
            .filter(RewardPool.location_id == normalized_location_id, RewardPool.channel_id == channel_id)
            .first()
        )
        if not pool:
            raise ValueError("override_loot_pool location_id not found for this channel")
