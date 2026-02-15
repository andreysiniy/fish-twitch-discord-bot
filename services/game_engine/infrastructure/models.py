from sqlalchemy import Column, Integer, String, Boolean, BigInteger, ForeignKey, Text, Float, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB  
from sqlalchemy.orm import relationship
from infrastructure.database import Base

class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, index=True)
    twitch_id = Column(String, unique=True, index=True)
    name = Column(String)
    is_active = Column(Boolean, default=True)
    
    config = Column(JSONB, default={})

    users_progress = relationship("UserProgress", back_populates="channel")
    reward_pools = relationship("RewardPool", back_populates="channel")
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
    
    # Инвентарь: {"equipped_rod": "basic_rod", "items": ["fish1", "boot"]}
    inventory = Column(JSONB, default={"items": [], "equipped_rod": None})

    channel = relationship("Channel", back_populates="users_progress")


class RewardPool(Base):
    __tablename__ = "reward_pools"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    location_id = Column(String, index=True) 
    location_name = Column(String, nullable=True)
    
    # [{"type": "points", "weight": 100, ...}, {"type": "item", ...}]
    rewards_data = Column(JSONB, default=[])
    requirements = Column(JSONB, default={})

    items_drop_rate = Column(Float, default=0.1)
    items = relationship("LocationItem", back_populates="pool")

    channel = relationship("Channel", back_populates="reward_pools")

class LocationItem(Base):
    __tablename__ = "location_items"

    id = Column(Integer, primary_key=True, index=True)
    reward_pool_id = Column(Integer, ForeignKey("reward_pools.id"))
    
    name = Column(String, nullable=False)
    item_id = Column(String, nullable=False) 
    description = Column(String)
    image_url = Column(String) 

    type = Column(String, default="fish", nullable=False)
    
    weight = Column(Integer, default=100) 
    rarity = Column(String, default="common")
    
    xp_gain = Column(Integer, default=0)
    
    quantity = Column(Integer, nullable=True) 
    
    message = Column(String, default="You caught {name}!")

    item_stats = Column(JSONB, default={})

    pool = relationship("RewardPool", back_populates="items")
