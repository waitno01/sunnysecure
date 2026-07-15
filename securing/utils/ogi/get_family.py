import logging

import httpx

from securing.utils.ogi.amc_headers import amc_api_headers

log = logging.getLogger(__name__)


async def get_family(session: httpx.AsyncClient, verification_token: str):
    try:
        family = await session.get(
            "https://account.microsoft.com/home/api/family/family-summary",
            headers=amc_api_headers(
                session,
                verification_token,
                qos_root="GLOBAL.HOME.FAMILY.GETFAMILYSUMMARY",
            ),
            follow_redirects=True,
        )
    except Exception:
        log.exception("get_family request failed")
        return {"members": []}

    body = family.text or ""
    if not body.strip():
        return {"members": []}
    try:
        data = family.json()
    except Exception:
        log.warning("get_family: non-JSON status=%s", family.status_code)
        return {"members": []}
    if not isinstance(data, dict):
        return {"members": []}
    if data.get("error") and not data.get("members"):
        log.warning("get_family: API error %s", data.get("error"))
        return {"members": []}
    data.setdefault("members", [])
    return data
