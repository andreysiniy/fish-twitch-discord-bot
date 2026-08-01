import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from infrastructure.database import Base

class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, index=True)
    twitch_id = Column(String, unique=True, index=True)
    name = Column(String)
    is_active = Column(Boolean, default=True)
    se_token = Column(String, nullable=True)
    se_channel_id = Column(String, nullable=True)
    
    config = Column(JSONB, default=dict, nullable=False)

    users_progress = relationship("UserProgress", back_populates="channel")
    reward_pools = relationship("RewardPool", back_populates="channel")
    item_definitions = relationship("ItemDefinition", back_populates="channel")
    fishing_events = relationship("FishingEvent", back_populates="channel")
    access_list = relationship(
        "ChannelAccessRole",
        back_populates="channel",
        cascade="all, delete-orphan"
    )


class ChannelAccessRole(Base):
    __tablename__ = "channel_access_roles"
    __table_args__ = (
        UniqueConstraint("channel_id", "user_twitch_id", name="uq_channel_user_access"),
    )

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    user_twitch_id = Column(String, nullable=False, index=True)
    user_twitch_name = Column(String, nullable=False, default="")
    role = Column(String, nullable=False, default="editor")

    channel = relationship("Channel", back_populates="access_list")


class UserProgress(Base):
    __tablename__ = "users_progress"
    __table_args__ = (
        UniqueConstraint("channel_id", "user_twitch_id", name="uq_user_progress_channel_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_twitch_id = Column(String, index=True)  
    username = Column(String)                    
    
    channel_id = Column(Integer, ForeignKey("channels.id"))
    
    level = Column(Integer, default=1)
    xp = Column(Integer, default=0)

    total_fish_stat = Column(Integer, default=0)
    total_mass_stat = Column(Numeric(18, 2), default=0, nullable=False)

    current_mass = Column(Numeric(18, 2), default=0, nullable=False)

    current_location_id = Column(String, default="default") 
    
    inventory = Column(
        JSONB,
        default=lambda: {"equipped_rod_slot": None, "max_slots": 20},
        nullable=False,
    )

    channel = relationship("Channel", back_populates="users_progress")
    items = relationship("InventoryItem", back_populates="owner", cascade="all, delete-orphan")


class ItemDefinition(Base):
    __tablename__ = "item_definitions"
    __table_args__ = (
        UniqueConstraint("channel_id", "item_id", name="uq_item_definitions_channel_item"),
    )

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    item_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    type = Column(String, default="equipment", nullable=False)
    slot = Column(String, nullable=True)
    rarity = Column(String, default="common", nullable=False)
    durability = Column(Integer, nullable=True)
    stack_size = Column(Integer, default=1, nullable=False)
    image_url = Column(String)
    base_stats = Column(JSONB, default=dict, nullable=False)
    is_sellable = Column(Boolean, default=True, nullable=False)
    is_tradeable = Column(Boolean, default=True, nullable=False)

    channel = relationship("Channel", back_populates="item_definitions")


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("user_id", "slot_id", name="uq_inventory_item_user_slot"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users_progress.id"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("item_definitions.id"), nullable=False, index=True)
    slot_id = Column(Integer, nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    current_durability = Column(Integer, nullable=True)
    meta = Column(JSONB, default=dict, nullable=False)

    definition = relationship("ItemDefinition", lazy="joined")
    owner = relationship("UserProgress", back_populates="items")


class RewardPool(Base):
    __tablename__ = "reward_pools"
    __table_args__ = (
        UniqueConstraint("channel_id", "location_id", name="uq_reward_pool_channel_location"),
    )

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    location_id = Column(String, index=True) 
    location_name = Column(String, nullable=True)
    
    rewards_data = Column(JSONB, default=list, nullable=False)
    requirements = Column(JSONB, default=dict, nullable=False)

    items_drop_rate = Column(Float, default=0.1)
    items = relationship("LocationItem", back_populates="pool")

    channel = relationship("Channel", back_populates="reward_pools")

class LocationItem(Base):
    __tablename__ = "location_items"

    id = Column(Integer, primary_key=True, index=True)
    reward_pool_id = Column(Integer, ForeignKey("reward_pools.id"))
    item_id = Column(Integer, ForeignKey("item_definitions.id"), nullable=False, index=True)
    weight = Column(Integer, default=100)
    xp_gain = Column(Integer, default=0, nullable=False)
    quantity = Column(Integer, nullable=True)
    message = Column(String, default="You caught {name}!")

    pool = relationship("RewardPool", back_populates="items")
    definition = relationship("ItemDefinition", lazy="joined")


class FishingEvent(Base):
    __tablename__ = "fishing_events"
    __table_args__ = (
        Index(
            "uq_fishing_events_active_per_channel",
            "channel_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    event_title = Column(String, nullable=False, default="Untitled Event")
    is_active = Column(Boolean, default=False, nullable=False)
    modifiers = Column(JSONB, default=dict, nullable=False)
    override_loot_pool = Column(String, nullable=True)

    channel = relationship("Channel", back_populates="fishing_events")


class EconomyOperation(Base):
    __tablename__ = "economy_operations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key = Column(String, unique=True, nullable=False, index=True)
    operation_type = Column(String, nullable=False)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users_progress.id"), nullable=False, index=True)
    twitch_username = Column(String, nullable=False)
    mass_delta = Column(Numeric(18, 2), nullable=False, default=0)
    points_delta = Column(Integer, nullable=False, default=0)
    state = Column(String, nullable=False, default="pending", index=True)
    external_applied = Column(Boolean, nullable=False, default=False)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    response_payload = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    idempotency_key = Column(String, unique=True, nullable=False, index=True)
    topic = Column(String, nullable=False, index=True)
    payload = Column(JSONB, default=dict, nullable=False)
    state = Column(String, nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    next_attempt_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    processed_at = Column(DateTime(timezone=True), nullable=True)
