import httpx
from anyio import to_thread
from core.config import settings
from infrastructure.repositories.channel_repo import ChannelRepository


class AuthService:
    def __init__(self, channel_repo: ChannelRepository):
        self.channel_repo = channel_repo

    async def authenticate_twitch_user(self, code: str, redirect_uri: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_url = "https://id.twitch.tv/oauth2/token"
            params = {
                "client_id": settings.TWITCH_CLIENT_ID,
                "client_secret": settings.TWITCH_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
            resp = await client.post(token_url, params=params)
            if resp.status_code != 200:
                raise ValueError("Failed to retrieve Twitch token")

            token_data = resp.json()
            access_token = str(token_data["access_token"])

            user_url = "https://api.twitch.tv/helix/users"
            headers = {
                "Client-ID": settings.TWITCH_CLIENT_ID,
                "Authorization": f"Bearer {access_token}",
            }
            user_resp = await client.get(user_url, headers=headers)
            if user_resp.status_code != 200:
                raise ValueError("Failed to retrieve user info")

            twitch_user = user_resp.json()["data"][0]

            channel = await to_thread.run_sync(
                self.channel_repo.get_by_twitch_id,
                twitch_user["id"],
            )
            is_streamer = channel is not None

            return {
                "twitch_id": twitch_user["id"],
                "username": twitch_user["login"],
                "is_streamer": is_streamer,
            }
