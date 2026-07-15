import logging

import httpx

from securing.utils.ogi.amc_headers import amc_api_headers

log = logging.getLogger(__name__)


async def get_devices(session: httpx.AsyncClient, verification_token: str):
    try:
        devices = await session.get(
            "https://account.microsoft.com/home/api/devices/devices-summary",
            headers=amc_api_headers(
                session,
                verification_token,
                qos_root="GLOBAL.HOME.DEVICES.GETDEVICESSUMMARYINFO",
            ),
            follow_redirects=True,
        )
    except Exception:
        log.exception("get_devices request failed")
        return {"devices": []}

    body = devices.text or ""
    if not body.strip():
        log.warning("get_devices: empty response status=%s", devices.status_code)
        return {"devices": []}

    try:
        data = devices.json()
    except Exception:
        log.warning(
            "get_devices: non-JSON status=%s snippet=%r",
            devices.status_code,
            body[:200],
        )
        return {"devices": []}

    if not isinstance(data, dict):
        return {"devices": []}
    if data.get("error") and not data.get("devices"):
        log.warning(
            "get_devices: API error status=%s error=%s",
            devices.status_code,
            data.get("error"),
        )
        return {"devices": []}
    data.setdefault("devices", [])
    return data
