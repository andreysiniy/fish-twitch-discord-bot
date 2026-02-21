import httpx


class SEApiClient:
    BASE_URL = "https://api.streamelements.com/kappa/v2/points"
    CHANNELS_ME_URL = "https://api.streamelements.com/kappa/v2/channels/me"

    async def get_balance(self, se_channel_id: str, plain_token: str, username: str) -> int:
        url = f"{self.BASE_URL}/{se_channel_id}/{username}"
        headers = self._build_headers(plain_token)

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)

        if response.status_code == 404:
            return 0
        if response.status_code in {401, 403}:
            raise PermissionError("Invalid Token")
        if response.status_code >= 400:
            raise ValueError("SE API Error")

        payload = response.json()
        return int(payload.get("points", 0) or 0)

    async def add_points(self, se_channel_id: str, plain_token: str, username: str, amount: int) -> None:
        url = f"{self.BASE_URL}/{se_channel_id}/{username}/{int(amount)}"
        headers = self._build_headers(plain_token)

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.put(url, headers=headers)

        if response.status_code in {401, 403}:
            raise PermissionError("Invalid Token")
        if response.status_code >= 400:
            raise ValueError("SE API Error")

    async def get_channel_id(self, plain_token: str) -> str:
        headers = self._build_headers(plain_token)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(self.CHANNELS_ME_URL, headers=headers)

        if response.status_code in {401, 403}:
            raise PermissionError("Invalid Token")
        if response.status_code >= 400:
            raise ValueError("SE API Error")

        payload = response.json()
        channel_id = self._extract_channel_id(payload)
        if not channel_id:
            raise ValueError("SE API Error")
        return channel_id

    def _build_headers(self, plain_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {plain_token}",
            "Content-Type": "application/json",
        }

    def _extract_channel_id(self, payload: object) -> str | None:
        if isinstance(payload, dict):
            value = payload.get("_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
            for nested in payload.values():
                nested_id = self._extract_channel_id(nested)
                if nested_id:
                    return nested_id
            return None

        if isinstance(payload, list):
            for nested in payload:
                nested_id = self._extract_channel_id(nested)
                if nested_id:
                    return nested_id
            return None

        return None
