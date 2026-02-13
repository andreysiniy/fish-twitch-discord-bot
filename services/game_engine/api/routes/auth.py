from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from services.auth_service import AuthService
from api.dependencies import get_auth_service
from core.security import create_access_token

router = APIRouter()

class TwitchLoginRequest(BaseModel):
    code: str
    redirect_uri: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    twitch_id: str
    is_streamer: bool

@router.post("/twitch", response_model=TokenResponse)
async def login_with_twitch(
    request: TwitchLoginRequest,
    service: AuthService = Depends(get_auth_service)
):
    try:
        user_data = await service.authenticate_twitch_user(request.code, request.redirect_uri)
        
        jwt_token = create_access_token(subject=user_data["twitch_id"])
        
        return TokenResponse(
            access_token=jwt_token,
            username=user_data["username"],
            twitch_id=user_data["twitch_id"],
            is_streamer=user_data["is_streamer"]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))