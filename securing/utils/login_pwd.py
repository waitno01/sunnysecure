import json
import logging

import httpx

log = logging.getLogger(__name__)


async def _try_vanguardflowtoken(
    session: httpx.AsyncClient, email: str, password: str
) -> str | None:
    """Best-effort checkpassword.srf. Returns token or None (never raises for soft fails)."""
    try:
        vanguard_response = await session.post(
            url="https://login.live.com/checkpassword.srf",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "checkpaswordflowtoken": "",
                "password": password,
                "username": email,
            },
        )
    except httpx.HTTPError as exc:
        # Real transport failure — let caller/proxy retry rotate sticky exit.
        log.warning("login_pwd: checkpassword transport error for %s: %s", email, exc)
        raise

    body = vanguard_response.text or ""
    status = vanguard_response.status_code

    if status >= 400 or not body.strip():
        log.warning(
            "login_pwd: checkpassword soft-fail status=%s for %s snippet=%r",
            status,
            email,
            body[:200],
        )
        print(f"[!] - checkpassword.srf status={status} — posting password without vanguard")
        return None

    try:
        token = vanguard_response.json().get("vanguardflowtoken")
    except (json.JSONDecodeError, TypeError, AttributeError):
        log.warning(
            "login_pwd: checkpassword non-JSON status=%s for %s snippet=%r",
            status,
            email,
            body[:200],
        )
        print("[!] - checkpassword.srf non-JSON — posting password without vanguard")
        return None

    if not token:
        print("[!] - VanguardFlowtoken None — posting password without vanguard")
        return None

    return token


async def login_pwd(session: httpx.AsyncClient, email: str, post_url: str, password: str, ppft: str) -> str:
    """Login with password.

    Prefer checkpassword.srf vanguard token when MS issues one. If checkpassword
    returns null / 400 / non-JSON (common under risk/rate-limit), fall back to a
    classic password post — raising would only burn proxies and never reach TOTP.
    """
    vanguardflowtoken = await _try_vanguardflowtoken(session, email, password)
    print(f"Got VanguardFlowtoken ({vanguardflowtoken})")

    payload: dict = {
        "type": 11,
        "login": email,
        "loginfmt": email,
        "passwd": password,
        "PPFT": ppft,
    }
    if vanguardflowtoken:
        payload["vanguardflowtoken"] = vanguardflowtoken

    password_post = await session.post(
        url=post_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=payload,
        follow_redirects=True,
    )

    return password_post.text
