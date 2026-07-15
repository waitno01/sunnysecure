import logging

import httpx

log = logging.getLogger(__name__)


async def get_owner_info(session: httpx.AsyncClient, verification_token: str):
    # Uses Profile RequestVerificationToken; falls back to AMC JWT claims.

    from securing.utils.ogi.owner_from_jwt import owner_info_from_amc_jwt
    from securing.utils.ogi.amc_headers import amc_api_headers

    headers = amc_api_headers(
        session,
        verification_token,
        qos_root="GLOBAL.PROFILE.PERSONALINFO.GETPERSONALINFO",
    )

    try:
        get_info = await session.get(
            "https://account.microsoft.com/profile/api/v1/personal-info",
            headers=headers,
        )
    except Exception:
        log.exception("get_owner_info request failed")
        return owner_info_from_amc_jwt(session)

    body = get_info.text or ""
    if not body.strip():
        log.warning("get_owner_info: empty status=%s", get_info.status_code)
        return owner_info_from_amc_jwt(session)

    try:
        data = get_info.json()
    except Exception:
        log.warning(
            "get_owner_info: non-JSON status=%s snippet=%r",
            get_info.status_code,
            body[:200],
        )
        return owner_info_from_amc_jwt(session)

    if not isinstance(data, dict):
        return owner_info_from_amc_jwt(session)

    # API returns {"error":"getPersonalInfoFailed"} when AMC session is incomplete
    if data.get("error") and not data.get("firstName") and not data.get("signInEmail"):
        log.warning(
            "get_owner_info: API error status=%s error=%s — using AMC JWT claims",
            get_info.status_code,
            data.get("error"),
        )
        return owner_info_from_amc_jwt(session)

    return data
