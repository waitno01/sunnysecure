import httpx

from minecraft.retry import TransientMCError, with_retries


async def _get_profile_once(ssid: str) -> dict | None:
    async with httpx.AsyncClient(timeout=30.0) as session:
        response = await session.get(
            url="https://api.minecraftservices.com/minecraft/profile",
            headers={"Authorization": f"Bearer {ssid}"},
        )

        if response.status_code in (408, 425, 429, 500, 502, 503, 504):
            raise TransientMCError(
                f"profile status {response.status_code}",
                status=response.status_code,
            )

        # 404 = no Java profile (real) — don't retry
        if response.status_code == 404:
            return None

        try:
            rjson = response.json()
        except Exception as exc:
            raise TransientMCError(f"profile non-JSON: {exc}") from exc

        if "name" in rjson:
            return {"name": rjson["name"], "uuid": rjson.get("id")}

        # Unexpected empty body / error shape — retry
        if response.status_code != 200:
            raise TransientMCError(f"profile unexpected status {response.status_code}")

        return None


async def get_profile(ssid: str) -> dict | None:
    return await with_retries(
        "get_profile",
        lambda: _get_profile_once(ssid),
        attempts=3,
        base_delay=2.0,
        retry_on_none=False,
    )
