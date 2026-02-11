from fastapi import Depends
from sqlalchemy.orm import Session

from infrastructure.database import SessionLocal
from infrastructure.repositories.user_repo import UserRepository
from infrastructure.repositories.config_repo import ConfigRepository
from infrastructure.repositories.cooldown_repo import CooldownRepository
from infrastructure.redis_client import RedisClient

from infrastructure.repositories.channel_repo import ChannelRepository
from services.admin_service import AdminService

from services.fishing_service import FishingService
from services.travel_service import TravelService

from services.inventory_service import InventoryService 

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user_repo(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)

def get_config_repo(db: Session = Depends(get_db)) -> ConfigRepository:
    return ConfigRepository(db)

def get_cooldown_repo() -> CooldownRepository:
    return CooldownRepository(redis_client=RedisClient.get_client())

def get_fishing_service(
    user_repo: UserRepository = Depends(get_user_repo),
    config_repo: ConfigRepository = Depends(get_config_repo),
    cooldown_repo: CooldownRepository = Depends(get_cooldown_repo)
) -> FishingService:
    return FishingService(
        user_repo=user_repo,
        config_repo=config_repo,
        cooldown_repo=cooldown_repo
    )

def get_travel_service(
    user_repo: UserRepository = Depends(get_user_repo),
    config_repo: ConfigRepository = Depends(get_config_repo)
) -> TravelService:
    return TravelService(user_repo=user_repo, config_repo=config_repo)

def get_channel_repo(db: Session = Depends(get_db)) -> ChannelRepository:
    return ChannelRepository(db)

def get_admin_service(
    repo: ChannelRepository = Depends(get_channel_repo),
    user_repo: UserRepository = Depends(get_user_repo),
    config_repo: ConfigRepository = Depends(get_config_repo)
) -> AdminService:
    return AdminService(repo, user_repo, config_repo)

def get_inventory_service(
    user_repo: UserRepository = Depends(get_user_repo)
) -> InventoryService:
    return InventoryService(user_repo)
