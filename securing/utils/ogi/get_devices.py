import logging

import httpx

log = logging.getLogger(__name__)


async def get_devices(session: httpx.AsyncClient, verification_token: str):
    # Uses Account VerificationToken

    try:
        devices = await session.get(
            "https://account.microsoft.com/home/api/devices/devices-summary",
            headers={
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "__RequestVerificationToken": verification_token,
                "Correlation-Context": (
                    "v=1,ms.b.tel.market=en-US,"
                    "ms.b.qos.rootOperationName=GLOBAL.HOME.DEVICES.GETDEVICESSUMMARYINFO"
                ),
            },
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
    data.setdefault("devices", [])
    return data
