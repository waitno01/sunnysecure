from dateutil import parser
import datetime
import httpx

from minecraft.retry import TransientMCError, with_retries


async def _get_username_info_once(ssid: str):
    async with httpx.AsyncClient(timeout=30.0) as session:
        response = await session.get(
            url="https://api.minecraftservices.com/minecraft/profile/namechange",
            headers={"Authorization": f"Bearer {ssid}"},
        )

        if response.status_code in (408, 425, 429, 500, 502, 503, 504):
            raise TransientMCError(
                f"namechange status {response.status_code}",
                status=response.status_code,
            )

        if response.status_code != 200:
            return False

        data = response.json()
        if data.get("nameChangeAllowed"):
            return False

        todayDate = datetime.datetime.now()
        changeDate = data.get("changedAt") or data.get("createdAt")
        if not changeDate:
            return False

        finalDate = (parser.parse(changeDate) + datetime.timedelta(days=31)).replace(tzinfo=None)
        return (finalDate - todayDate).days


async def get_username_info(ssid: str):
    return await with_retries(
        "get_username_info",
        lambda: _get_username_info_once(ssid),
        attempts=3,
        base_delay=1.5,
        retry_on_none=False,
    )
