import secrets
from urllib.parse import urlencode

from anyio import to_thread
from api.dependencies import get_auth_service
from core.config import settings
from core.security import create_access_token
from fastapi import APIRouter, Depends, HTTPException
from infrastructure.redis_client import RedisClient
from pydantic import BaseModel
from services.auth_service import AuthService

router = APIRouter()


class TwitchLoginRequest(BaseModel):
    code: str
    redirect_uri: str
    state: str


class TwitchLoginStartRequest(BaseModel):
    redirect_uri: str


class TwitchLoginStartResponse(BaseModel):
    authorization_url: str
    state: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    twitch_id: str
    is_streamer: bool


@router.post("/twitch/start", response_model=TwitchLoginStartResponse)
def start_twitch_login(request: TwitchLoginStartRequest) -> TwitchLoginStartResponse:
    _validate_redirect_uri(request.redirect_uri)
    state = secrets.token_urlsafe(32)
    RedisClient.get_client().setex(f"oauth:twitch:{state}", 600, request.redirect_uri)
    query = urlencode(
        {
            "client_id": settings.TWITCH_CLIENT_ID,
            "redirect_uri": request.redirect_uri,
            "response_type": "code",
            "scope": "user:read:email",
            "state": state,
        }
    )
    return TwitchLoginStartResponse(
        authorization_url=f"https://id.twitch.tv/oauth2/authorize?{query}",
        state=state,
    )


@router.post("/twitch", response_model=TokenResponse)
async def login_with_twitch(
    request: TwitchLoginRequest, service: AuthService = Depends(get_auth_service)
):
    _validate_redirect_uri(request.redirect_uri)
    stored_redirect_uri = await to_thread.run_sync(
        RedisClient.get_client().getdel,
        f"oauth:twitch:{request.state}",
    )
    if not stored_redirect_uri or stored_redirect_uri != request.redirect_uri:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    try:
        user_data = await service.authenticate_twitch_user(request.code, request.redirect_uri)

        jwt_token = create_access_token(subject=user_data["twitch_id"])

        return TokenResponse(
            access_token=jwt_token,
            username=user_data["username"],
            twitch_id=user_data["twitch_id"],
            is_streamer=user_data["is_streamer"],
        )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Twitch authentication failed") from error


def _validate_redirect_uri(redirect_uri: str) -> None:
    if redirect_uri not in settings.twitch_oauth_redirect_uris:
        raise HTTPException(status_code=400, detail="redirect_uri is not allowed")
# ruff: noqa: B008
