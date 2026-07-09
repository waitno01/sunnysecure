import httpx

from minecraft.retry import TransientMCError, with_retries


async def _get_method_once(ssid: str) -> str | None:
    async with httpx.AsyncClient(timeout=30.0) as session:
        licenses = await session.get(
            url="https://api.minecraftservices.com/entitlements/license?requestId=c24114ab-1814-4d5c-9b1f-e8825edaec1f",
            headers={"Authorization": f"Bearer {ssid}"},
        )

        if licenses.status_code in (408, 425, 429, 500, 502, 503, 504):
            raise TransientMCError(
                f"entitlements status {licenses.status_code}",
                status=licenses.status_code,
            )

        try:
            licenses_json = licenses.json()
        except Exception as exc:
            raise TransientMCError(f"entitlements non-JSON: {exc}") from exc

        if "items" in licenses_json:
            for item in licenses_json["items"]:
                if item["name"] in ("product_minecraft", "game_minecraft"):
                    if item["source"] == "GAMEPASS":
                        return "Gamepass"
                    if item["source"] in ("PURCHASE", "MC_PURCHASE"):
                        return "Purchased"

        return None


async def get_method(ssid: str) -> str | None:
    return await with_retries(
        "get_method",
        lambda: _get_method_once(ssid),
        attempts=3,
        base_delay=1.5,
        retry_on_none=False,
    )
