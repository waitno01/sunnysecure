import logging
import json
from datetime import date, datetime

import httpx

from securing.utils.ogi.amc_headers import amc_api_headers

log = logging.getLogger(__name__)


def _empty() -> dict:
    return {"active": [], "canceled": [], "commercial": []}


def _parse_date(raw) -> date | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"no renewal date", "none", "null", "n/a"}:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(text.replace("Z", "")[:19], fmt).date()
        except ValueError:
            continue
    return None


def _is_dead_cycle(s: dict) -> bool:
    """Expired / ended payment cycle — not a live entitlement."""
    status = str(s.get("status") or s.get("subscriptionStatus") or "").lower()
    auto = s.get("autoRenew")
    renewal_raw = s.get("nextRenewalDate") or s.get("renewalDate") or ""
    renewal = str(renewal_raw).lower()
    today = date.today()

    if (
        "expir" in status
        or "ended" in status
        or "inactive" in status
        or "lapsed" in status
        or "deactivat" in status
    ):
        return True
    if "cancel" in status and "active" not in status:
        return True
    # Past renewal / end date
    for key in (
        "expirationDate",
        "expiryDate",
        "endDate",
        "expiresOn",
        "validUntil",
        "nextRenewalDate",
        "renewalDate",
    ):
        parsed = _parse_date(s.get(key))
        if parsed is not None and parsed < today:
            return True
    if auto is False and (
        not renewal or "no renewal" in renewal or renewal in {"none", "null"}
    ):
        return True
    return False


def _map_payment_transactions(data: dict | list) -> dict | None:
    """Normalize paymentinstruments paymentTransactions → active/canceled/commercial."""
    if isinstance(data, list):
        subs = data
    elif isinstance(data, dict):
        if data.get("error") and not data.get("subscriptions"):
            return None
        # Prefer raw list so we can re-bucket expired items MS left in "active"
        subs = data.get("subscriptions")
        if not isinstance(subs, list):
            # Already bucketed — still re-classify each item
            merged: list = []
            for key in ("active", "canceled", "commercial", "subscriptions"):
                items = data.get(key) or []
                if isinstance(items, list):
                    merged.extend(items)
            if not merged and (data.get("active") is not None or data.get("canceled") is not None):
                # Empty but valid shape
                return {
                    "active": data.get("active") or [],
                    "canceled": data.get("canceled") or [],
                    "commercial": data.get("commercial") or [],
                }
            subs = merged
        if not isinstance(subs, list):
            return None
    else:
        return None

    active, canceled, commercial = [], [], []
    for s in subs:
        if not isinstance(s, dict):
            continue
        title = str(
            s.get("title")
            or s.get("productName")
            or s.get("productTitle")
            or s.get("name")
            or ""
        ).lower()
        status = str(s.get("status") or s.get("subscriptionStatus") or "").lower()
        auto = s.get("autoRenew")
        renewal = str(s.get("nextRenewalDate") or s.get("renewalDate") or "")
        # Expired / ended → canceled. Still-entitled cancel-at-period-end (future
        # end date, often autoRenew=false) stays active so we still reject real GP.
        if _is_dead_cycle(s):
            bucket = canceled
        elif "commercial" in status or s.get("isCommercial"):
            bucket = commercial
        else:
            bucket = active
        bucket.append(s)
        if "game" in title and "pass" in title:
            log.info(
                "map sub title=%r status=%r autoRenew=%r renewal=%r -> %s",
                title[:80],
                status,
                auto,
                renewal[:40],
                "canceled" if bucket is canceled else ("commercial" if bucket is commercial else "active"),
            )
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
