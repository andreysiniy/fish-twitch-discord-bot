from typing import Any, Dict, Optional, Tuple

import aiohttp
import os

API_KEY = os.getenv("BOT_API_KEY", "")

class EngineApiError(Exception):
    pass


class EngineApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def fish(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request("POST", "/v1/fish", json=payload)

    async def fish_travel(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request("POST", "/v1/fishtravel", json=payload)

    async def fish_cooldown(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request("POST", "/v1/fishcd", json=payload)

    async def fish_stats(self, channel_id: str, user_id: str, username: str | None = None) -> Dict[str, Any]:
        path = f"/v1/fishstats/{channel_id}/{user_id}"
        if username:
            path = f"{path}?username={username}"
        return await self._request("GET", path)

    async def fish_top(self, channel_id: str, limit: int = 10, mode: str = "current") -> Dict[str, Any]:
        return await self._request("GET", f"/v1/fishtop/{channel_id}?limit={limit}&mode={mode}")

    async def get_inventory(self, channel_id: str, user_id: str) -> Dict[str, Any]:
        return await self._request("GET", f"/v1/inventory/{channel_id}/{user_id}")

    async def equip_item(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request("POST", "/v1/inventory/equip", json=payload)

    async def admin_list_moderators(self, channel_id: str, actor_twitch_id: str) -> Dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/admin/channels/{channel_id}/moderators/list",
            json={"actor_twitch_id": actor_twitch_id}
        )

    async def admin_upsert_moderator(
        self,
        channel_id: str,
        actor_twitch_id: str,
        user_twitch_id: str,
        user_twitch_name: str,
        role: str
    ) -> Dict[str, Any]:
        payload = {
            "actor_twitch_id": actor_twitch_id,
            "user_twitch_id": user_twitch_id,
            "user_twitch_name": user_twitch_name,
            "role": role,
        }
        return await self._request(
            "POST",
            f"/v1/admin/channels/{channel_id}/moderators/upsert",
            json=payload
        )

    async def admin_remove_moderator(
        self,
        channel_id: str,
        actor_twitch_id: str,
        user_twitch_id: str
    ) -> Dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/admin/channels/{channel_id}/moderators/remove",
            json={
                "actor_twitch_id": actor_twitch_id,
                "user_twitch_id": user_twitch_id,
            }
        )

    async def admin_set_fish_cooldown(
        self,
        channel_id: str,
        actor_twitch_id: str,
        seconds: int,
        scope: str | None = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "actor_twitch_id": actor_twitch_id,
            "seconds": int(seconds),
        }
        if scope:
            payload["scope"] = scope
        return await self._request(
            "POST",
            f"/v1/admin/channels/{channel_id}/fishcd/set",
            json=payload
        )
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-API-KEY": API_KEY
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        await self.start()
        if self._session is None:
            raise EngineApiError("HTTP session is not initialized")

        url = f"{self.base_url}{path}"
        async with self._session.request(
            method,
            url,
            json=json,
            headers=self._get_headers()
        ) as response:
            print(f"Request: {method} {url} - Status: {response.status}, headers: {response.headers}")
            data, text = await self._read_payload(response)
            if response.status >= 400:
                detail = data.get("detail") if isinstance(data, dict) else text
                raise EngineApiError(f"{detail}")

            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {"items": data}
            return {"raw": text}

    async def _read_payload(self, response: aiohttp.ClientResponse) -> Tuple[Any, str]:
        text = await response.text()
        try:
            return await response.json(content_type=None), text
        except Exception:
            return {"raw": text}, text
