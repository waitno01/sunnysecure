import logging

import httpx

from securing.utils.ogi.amc_headers import amc_api_headers

log = logging.getLogger(__name__)


def _empty() -> dict:
    return {"active": [], "canceled": [], "commercial": []}


def _map_payment_transactions(data: dict | list) -> dict | None:
    """Normalize paymentinstruments paymentTransactions → active/canceled/commercial."""
    if isinstance(data, list):
        subs = data
    elif isinstance(data, dict):
        if data.get("error") and not data.get("subscriptions"):
            return None
        subs = data.get("subscriptions") or data.get("active") or []
        if data.get("active") is not None or data.get("canceled") is not None:
            out = {
                "active": data.get("active") or [],
                "canceled": data.get("canceled") or [],
                "commercial": data.get("commercial") or [],
            }
            return out
    else:
        return None

    active, canceled, commercial = [], [], []
    for s in subs if isinstance(subs, list) else []:
        if not isinstance(s, dict):
            continue
        status = str(s.get("status") or s.get("subscriptionStatus") or "").lower()
        auto = s.get("autoRenew")
        bucket = active
        if "cancel" in status or auto is False:
            bucket = canceled
        elif "commercial" in status or s.get("isCommercial"):
            bucket = commercial
        bucket.append(s)
    return {"active": active, "canceled": canceled, "commercial": commercial}


async def _via_msadelegate(session: httpx.AsyncClient) -> dict | None:
    from securing.utils.cookies.get_msadelegate import get_msadelegate

    token = await get_msadelegate(session)
    if not token:
        return None
    try:
        resp = await session.get(
            "https://paymentinstruments.mp.microsoft.com/v6.0/users/me/paymentTransactions",
            headers={
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Authorization": f"MSADELEGATE1.0={token}",
            },
            follow_redirects=True,
        )
    except Exception:
        log.exception("get_subscriptions msadelegate request failed")
        return None

    body = resp.text or ""
    if not body.strip():
        log.warning("get_subscriptions msadelegate: empty status=%s", resp.status_code)
        return None
    try:
        data = resp.json()
    except Exception:
        log.warning(
            "get_subscriptions msadelegate: non-JSON status=%s snippet=%r",
            resp.status_code,
            body[:200],
        )
        return None

    mapped = _map_payment_transactions(data)
    if mapped is not None:
        print(
            f"[+] - Subscriptions via MSADELEGATE "
            f"(active={len(mapped['active'])}, canceled={len(mapped['canceled'])})"
        )
    return mapped


async def get_subscriptions(session: httpx.AsyncClient, verification_token: str):
    # Prefer paymentinstruments (dona path); fall back to account.microsoft.com.

    via_pi = await _via_msadelegate(session)
    if via_pi is not None:
        return via_pi

    try:
        subscriptions = await session.get(
            "https://account.microsoft.com/services/api/subscriptions"
            "?excludeWindowsStoreInstallOptions=false"
            "&excludeLegacySubscriptions=true"
            "&isReact=true"
            "&includeCmsData=false",
            headers=amc_api_headers(
                session,
                verification_token,
                qos_root="GLOBAL.SERVICES.GETSUBSCRIPTIONS",
            ),
        )
    except Exception:
        log.exception("get_subscriptions request failed")
        return _empty()

    body = subscriptions.text or ""
    if not body.strip():
        log.warning("get_subscriptions: empty status=%s", subscriptions.status_code)
        return _empty()

    try:
        data = subscriptions.json()
    except Exception:
        log.warning(
            "get_subscriptions: non-JSON status=%s snippet=%r",
            subscriptions.status_code,
            body[:200],
        )
        return _empty()

    if not isinstance(data, dict):
        return _empty()

    if data.get("error") and not any(
        data.get(k) for k in ("active", "canceled", "commercial", "subscriptions")
    ):
        log.warning(
            "get_subscriptions: API error status=%s error=%s",
            subscriptions.status_code,
            data.get("error"),
        )
        return _empty()

    data.setdefault("active", [])
    data.setdefault("canceled", [])
    data.setdefault("commercial", [])
    return data
