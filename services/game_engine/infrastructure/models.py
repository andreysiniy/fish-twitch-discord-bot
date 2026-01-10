from sqlalchemy import Column, Integer, String, Boolean, BigInteger, ForeignKey, Text
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


class UserProgress(Base):
    __tablename__ = "users_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_twitch_id = Column(String, index=True)  
    username = Column(String)                    
    
    channel_id = Column(Integer, ForeignKey("channels.id"))
    
    level = Column(Integer, default=1)
    xp = Column(Integer, default=0)
    current_location_id = Column(String, default="default") 
    
    # Инвентарь: {"equipped_rod": "basic_rod", "items": ["fish1", "boot"]}
    inventory = Column(JSONB, default={"items": [], "equipped_rod": None})

    channel = relationship("Channel", back_populates="users_progress")


class RewardPool(Base):
    __tablename__ = "reward_pools"

    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    location_id = Column(String, index=True) 
    
    # [{"type": "points", "weight": 100, ...}, {"type": "item", ...}]
    rewards_data = Column(JSONB, default=[])

    channel = relationship("Channel", back_populates="reward_pools")