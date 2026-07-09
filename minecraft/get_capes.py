import httpx

from minecraft.retry import TransientMCError, with_retries


async def _get_capes_once(ssid: str) -> list:
    async with httpx.AsyncClient(timeout=30.0) as session:
        response = await session.get(
            url="https://api.minecraftservices.com/minecraft/profile",
            headers={"Authorization": f"Bearer {ssid}"},
        )

        if response.status_code in (408, 425, 429, 500, 502, 503, 504):
            raise TransientMCError(
                f"capes status {response.status_code}",
                status=response.status_code,
            )

        if response.status_code == 404:
            return []

        if response.status_code != 200:
            raise TransientMCError(f"capes unexpected status {response.status_code}")

        jresponse = response.json()
        capes = jresponse.get("capes")
        return capes if isinstance(capes, list) else []


async def get_capes(ssid: str) -> list:
    result = await with_retries(
        "get_capes",
        lambda: _get_capes_once(ssid),
        attempts=3,
        base_delay=1.5,
        retry_on_none=False,
    )
    return result if isinstance(result, list) else []
