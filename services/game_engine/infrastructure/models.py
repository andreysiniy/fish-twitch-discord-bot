from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Float, UniqueConstraint
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
    
    config = Column(JSONB, default={})

    users_progress = relationship("UserProgress", back_populates="channel")
    reward_pools = relationship("RewardPool", back_populates="channel")
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

    id = Column(Integer, primary_key=True, index=True)
    user_twitch_id = Column(String, index=True)  
    username = Column(String)                    
    
    channel_id = Column(Integer, ForeignKey("channels.id"))
    
    level = Column(Integer, default=1)
    xp = Column(Integer, default=0)

    total_fish_stat = Column(Integer, default=0)
    total_mass_stat = Column(Float, default=0.0)

    current_mass = Column(Float, default=0.0)

    current_location_id = Column(String, default="default") 
    
    inventory = Column(JSONB, default={"equipped_rod_slot": None, "max_slots": 20})

    channel = relationship("Channel", back_populates="users_progress")
    items = relationship("InventoryItem", back_populates="owner", cascade="all, delete-orphan")


class ItemDefinition(Base):
    __tablename__ = "item_definitions"
    __table_args__ = (
        UniqueConstraint("channel_twitch_id", "item_id", name="uq_item_definitions_channel_item"),
    )

    id = Column(String, primary_key=True, index=True)
    channel_twitch_id = Column(String, nullable=False, index=True)
    item_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    type = Column(String, default="equipment", nullable=False)
    slot = Column(String, nullable=True)
    rarity = Column(String, default="common", nullable=False)
    durability = Column(Integer, nullable=True)
    stack_size = Column(Integer, default=1, nullable=False)
    image_url = Column(String)
    base_stats = Column(JSONB, default={})
    is_sellable = Column(Boolean, default=True, nullable=False)
    is_tradeable = Column(Boolean, default=True, nullable=False)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users_progress.id"), nullable=False, index=True)
    item_id = Column(String, ForeignKey("item_definitions.id"), nullable=False, index=True)
    slot_id = Column(Integer, nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    current_durability = Column(Integer, nullable=True)
    meta = Column(JSONB, default={})

    definition = relationship("ItemDefinition", lazy="joined")
    owner = relationship("UserProgress", back_populates="items")


class RewardPool(Base):
    __tablename__ = "reward_pools"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    location_id = Column(String, index=True) 
    location_name = Column(String, nullable=True)
    
    rewards_data = Column(JSONB, default=[])
    requirements = Column(JSONB, default={})

    items_drop_rate = Column(Float, default=0.1)
    items = relationship("LocationItem", back_populates="pool")

    channel = relationship("Channel", back_populates="reward_pools")

class LocationItem(Base):
    __tablename__ = "location_items"

    id = Column(Integer, primary_key=True, index=True)
    reward_pool_id = Column(Integer, ForeignKey("reward_pools.id"))
    item_id = Column(String, ForeignKey("item_definitions.id"), nullable=False, index=True)
    weight = Column(Integer, default=100)
    xp_gain = Column(Integer, default=0, nullable=False)
    quantity = Column(Integer, nullable=True)
    message = Column(String, default="You caught {name}!")

    pool = relationship("RewardPool", back_populates="items")
    definition = relationship("ItemDefinition", lazy="joined")


class FishingEvent(Base):
    __tablename__ = "fishing_events"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False, index=True)
    event_title = Column(String, nullable=False, default="Untitled Event")
    is_active = Column(Boolean, default=False, nullable=False)
    modifiers = Column(JSONB, default={})
    override_loot_pool = Column(String, nullable=True)

    channel = relationship("Channel", back_populates="fishing_events")
