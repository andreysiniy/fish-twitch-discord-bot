from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from sqlalchemy.orm import Session

from infrastructure.after_commit import run_after_commit_callbacks
from infrastructure.database import SessionLocal
from infrastructure.repositories.user_repo import UserRepository
from infrastructure.repositories.config_repo import ConfigRepository
from infrastructure.repositories.cooldown_repo import CooldownRepository
from infrastructure.redis_client import RedisClient
from infrastructure.repositories.channel_repo import ChannelRepository
from infrastructure.se_client import SEApiClient

from services.admin_service import AdminService
from services.auth_service import AuthService
from services.economy_service import EconomyService
from services.fishing_service import FishingService
from services.travel_service import TravelService
from services.inventory_service import InventoryService
from services.external_action_service import ExternalActionService
from services.discord_admin_service import DiscordAdminService
from services.streamelements_integration_service import StreamElementsIntegrationService

from core.security import decode_access_token
from core.config import settings

_SE_CLIENT = SEApiClient()


def get_db():
    db = SessionLocal()
    db.info.setdefault("after_commit_callbacks", [])
    try:
        yield db
        db.commit()
        run_after_commit_callbacks(db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


jwt_scheme = HTTPBearer(auto_error=False)
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_user_repo(db: Session = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


def get_config_repo(db: Session = Depends(get_db)) -> ConfigRepository:
    return ConfigRepository(db)


def get_cooldown_repo(db: Session = Depends(get_db)) -> CooldownRepository:
    return CooldownRepository(redis_client=RedisClient.get_client(), db=db)


def get_channel_repo(db: Session = Depends(get_db)) -> ChannelRepository:
    return ChannelRepository(db)


def get_fishing_service(
    user_repo: UserRepository = Depends(get_user_repo),
    config_repo: ConfigRepository = Depends(get_config_repo),
    cooldown_repo: CooldownRepository = Depends(get_cooldown_repo),
    channel_repo: ChannelRepository = Depends(get_channel_repo),
) -> FishingService:
    return FishingService(
        user_repo=user_repo,
        config_repo=config_repo,
        cooldown_repo=cooldown_repo,
        channel_repo=channel_repo,
    )


def get_travel_service(
    user_repo: UserRepository = Depends(get_user_repo),
    config_repo: ConfigRepository = Depends(get_config_repo),
) -> TravelService:
    return TravelService(user_repo=user_repo, config_repo=config_repo)


def get_admin_service(
    repo: ChannelRepository = Depends(get_channel_repo),
    user_repo: UserRepository = Depends(get_user_repo),
    config_repo: ConfigRepository = Depends(get_config_repo),
) -> AdminService:
    return AdminService(repo, user_repo, config_repo, se_client=_SE_CLIENT)


def get_inventory_service(user_repo: UserRepository = Depends(get_user_repo)) -> InventoryService:
    return InventoryService(user_repo)


def get_auth_service(channel_repo: ChannelRepository = Depends(get_channel_repo)) -> AuthService:
    return AuthService(channel_repo)


def get_external_action_service(
    channel_repo: ChannelRepository = Depends(get_channel_repo),
) -> ExternalActionService:
    return ExternalActionService(channel_repo)


def get_discord_admin_service(db: Session = Depends(get_db)) -> DiscordAdminService:
    return DiscordAdminService(db)


def get_streamelements_integration_service(
    db: Session = Depends(get_db),
) -> StreamElementsIntegrationService:
    return StreamElementsIntegrationService(db, se_client=_SE_CLIENT)


def get_economy_service(
    user_repo: UserRepository = Depends(get_user_repo),
    channel_repo: ChannelRepository = Depends(get_channel_repo),
) -> EconomyService:
    return EconomyService(
        user_repo=user_repo,
        channel_repo=channel_repo,
        se_client=_SE_CLIENT,
    )


async def get_current_user_id(
    auth: HTTPAuthorizationCredentials | None = Depends(jwt_scheme),
) -> str:
    if not auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth.credentials

    twitch_id = decode_access_token(token)
    if not twitch_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return twitch_id


async def verify_security(
    auth: HTTPAuthorizationCredentials | None = Depends(jwt_scheme),
    x_api_key: str | None = Security(api_key_scheme),
) -> str | None:
    if x_api_key == settings.BOT_API_KEY:
        return "BOT_SERVICE"

    if auth and auth.credentials:
        token = auth.credentials
        user_id = decode_access_token(token)
        if user_id:
            return user_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
    )
