"""Acquire MSADELEGATE token for paymentinstruments.mp.microsoft.com APIs.

Dona uses this for subscriptions + payment cards. account.microsoft.com
home APIs often 401 without a finished MSAL bridge; pidl on-behalf-of
still works once AMCSecAuthJWT is present.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


async def get_msadelegate(session: httpx.AsyncClient) -> str | None:
    try:
        resp = await session.get(
            "https://account.microsoft.com/auth/acquire-onbehalf-of-token?scopes=pidl",
            headers={
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
            },
            follow_redirects=True,
            timeout=_TIMEOUT,
        )
    except Exception:
        log.exception("get_msadelegate request failed")
        return None

    try:
        data = resp.json()
    except Exception:
        log.warning(
            "get_msadelegate: non-JSON status=%s snippet=%r",
            resp.status_code,
            (resp.text or "")[:200],
        )
        return None

    if isinstance(data, list) and data:
        token_data = data[0]
        if isinstance(token_data, dict) and token_data.get("isSuccess") and token_data.get("token"):
            print("[+] - Got MSADELEGATE (pidl)")
            return token_data["token"]

    log.warning("get_msadelegate: no token status=%s data=%r", resp.status_code, data)
    return None
