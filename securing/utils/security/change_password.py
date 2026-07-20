"""Set Microsoft password while already logged into account.live.com."""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import unquote

import httpx

logger = logging.getLogger(__name__)

# manageProofs.urls.changePassword.apiId
_CHANGE_HPGID = "201052"


def _decode(raw: str) -> str:
    raw = unquote(raw or "")
    try:
        return json.loads(f'"{raw}"')
    except Exception:
        return (
            raw.replace("\\/", "/")
            .replace('\\"', '"')
            .replace("\\u002b", "+")
            .replace("\\u003d", "=")
        )


def _find_canary(html: str) -> str | None:
    for pat in (
        r'"apiCanary"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'name="canary"[^>]*value="([^"]+)"',
        r'"canary"\s*:\s*"((?:\\.|[^"\\])*)"',
    ):
        m = re.search(pat, html or "", re.I)
        if m:
            return _decode(m.group(1))
    return None


def _find_user_ticket(html: str) -> str | None:
    """Extract ChangePassword userTicket / iPostedTicket from page HTML."""
    for pat in (
        r'id="iPostedTicket"[^>]*value="([^"]+)"',
        r'name="iPostedTicket"[^>]*value="([^"]+)"',
        # Prefer page ticket over addPassword.postTicket (passwordless-only)
        r'"sPostedTicket"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"postedTicket"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"postTicket"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"userTicket"\s*:\s*"((?:\\.|[^"\\])*)"',
    ):
        m = re.search(pat, html or "", re.I)
        if m:
            ticket = _decode(m.group(1))
            if ticket and len(ticket) > 20:
                return ticket
    return None


def _find_token(html: str) -> str | None:
    for pat in (
        r'"sRecoveryToken"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'"token"\s*:\s*"(a:[^"]+)"',
        r'name="t"[^>]*value="([^"]+)"',
    ):
        m = re.search(pat, html or "", re.I)
        if m:
            tok = _decode(m.group(1))
            if tok and len(tok) > 10:
                return tok
    return None


def _ms_headers(canary: str, *, referer: str) -> dict:
    return {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "canary": canary,
        "Canary": canary,
        "Origin": "https://account.live.com",
        "Referer": referer,
        "hpgid": _CHANGE_HPGID,
        "hpgact": "0",
        "uiflvr": "1001",
        "scid": "100109",
        "x-ms-apiVersion": "2",
        "x-ms-apiTransport": "xhr",
        "X-Requested-With": "XMLHttpRequest",
    }


def _ok_response(data: dict | None, label: str) -> bool:
    if not isinstance(data, dict):
        return False
    err = data.get("error")
    if err:
        code = err.get("code") if isinstance(err, dict) else err
        logger.error("%s error=%s body=%s", label, code, str(data)[:300])
        print(f"[X] - {label} error: {code}")
        return False
    logger.info("%s OK keys=%s", label, list(data)[:8])
    print(f"[+] - {label} OK (authenticated)")
    return True


async def change_password_authenticated(
    session: httpx.AsyncClient,
    new_password: str,
    *,
    current_password: str | None = None,
) -> bool:
    """Set password via authenticated account.live.com APIs.

    Tries ``/API/ChangePassword`` then ``/API/Recovery/ResetPassword``.
    Prefer ``password/Change`` page tickets — manage ``addPassword.postTicket``
    is for passwordless add and returns MS error 500 on normal accounts.
    """
    new_password = (new_password or "").strip()
    if not new_password:
        return False

    page_html = ""
    canary = None
    ticket = None
    token = None
    referer = "https://account.live.com/password/Change"

    for url in (
        "https://account.live.com/password/Change",
        "https://account.live.com/password/change",
        "https://account.live.com/proofs/Manage",
    ):
        try:
            resp = await session.get(
                url,
                headers={"host": "account.live.com"},
                follow_redirects=True,
            )
            html = resp.text or ""
        except Exception:
            logger.exception("ChangePassword GET %s failed", url)
            continue

        page_html = html
        canary = _find_canary(html) or canary
        # For manage page, only take iPostedTicket — skip addPassword.postTicket
        if "password/Change" in url.lower() or "password/change" in url.lower():
            ticket = _find_user_ticket(html) or ticket
            token = _find_token(html) or token
            referer = str(resp.url)
        else:
            # Manage: only HTML iPostedTicket, not JSON postTicket
            m = re.search(
                r'id="iPostedTicket"[^>]*value="([^"]+)"', html or "", re.I
            ) or re.search(
                r'name="iPostedTicket"[^>]*value="([^"]+)"', html or "", re.I
            )
            if m:
                ticket = _decode(m.group(1)) or ticket
            canary = _find_canary(html) or canary

        if canary and ticket:
            break

    if not canary or not ticket:
        logger.error(
            "ChangePassword missing canary/ticket (canary=%s ticket=%s html_len=%s)",
            bool(canary),
            bool(ticket),
            len(page_html),
        )
        print("[X] - ChangePassword: missing canary/ticket on manage pages")
        return False

    payloads = [
        {"userTicket": ticket, "password": new_password},
        {
            "userTicket": ticket,
            "password": new_password,
            "enableExpiration": None,
            "needsSlt": False,
        },
    ]
    if current_password:
        payloads.append(
            {
                "userTicket": ticket,
                "password": new_password,
                "currentPassword": current_password,
                "enableExpiration": None,
            }
        )
    if token:
        payloads.append(
            {
                "token": token,
                "password": new_password,
                "userTicket": ticket,
                "needsSlt": False,
                "expiryEnabled": None,
            }
        )

    endpoints = (
        ("ChangePassword", "https://account.live.com/API/ChangePassword"),
        ("ResetPassword", "https://account.live.com/API/Recovery/ResetPassword"),
    )

    headers = _ms_headers(canary, referer=referer)
    for label, endpoint in endpoints:
        for payload in payloads:
            try:
                resp = await session.post(endpoint, json=payload, headers=headers)
            except Exception:
                logger.exception("%s POST failed", label)
                continue
            try:
                data = resp.json()
            except Exception:
                logger.error(
                    "%s non-JSON status=%s body=%s",
                    label,
                    resp.status_code,
                    (resp.text or "")[:300],
                )
                continue
            if _ok_response(data, label):
                return True
            # refresh canary if MS rotated it
            if isinstance(data, dict) and data.get("apiCanary"):
                headers = _ms_headers(str(data["apiCanary"]), referer=referer)

    print("[X] - Authenticated password change failed on all endpoints")
    return False
