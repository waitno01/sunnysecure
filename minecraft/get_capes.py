import httpx


async def get_capes(ssid: str):
    async with httpx.AsyncClient(timeout=None) as session:
        response = await session.get(
            url="https://api.minecraftservices.com/minecraft/profile",
            headers={
                "Authorization": f"Bearer {ssid}"
            },
        )

        if response.status_code != 200:
            return []

        jresponse = response.json()
        capes = jresponse.get("capes")
        return capes if isinstance(capes, list) else []
