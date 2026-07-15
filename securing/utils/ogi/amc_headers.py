"""Shared AMC API request headers (RequestVerificationToken + optional Bearer)."""

from __future__ import annotations

import httpx

from securing.utils.cookies.safe_cookies import get_cookie


def amc_api_headers(
    session: httpx.AsyncClient,
    verification_token: str | None,
    *,
    qos_root: str,
) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Correlation-Context": (
            f"v=1,ms.b.tel.market=en-US,ms.b.qos.rootOperationName={qos_root}"
        ),
    }
    if verification_token:
        headers["__RequestVerificationToken"] = verification_token
    jwt = get_cookie(session, "AMCSecAuthJWT")
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    return headers
