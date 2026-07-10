import json
import logging

import httpx

log = logging.getLogger(__name__)


async def login_pwd(session: httpx.AsyncClient, email: str, post_url: str, password: str, ppft: str) -> str:
    # Login with Password

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

    body = vanguard_response.text or ""
    if not body.strip():
        log.error(
            "login_pwd: empty checkpassword.srf response status=%s for %s",
            vanguard_response.status_code,
            email,
        )
        raise httpx.RemoteProtocolError(
            f"checkpassword.srf empty response (status={vanguard_response.status_code})"
        )

    try:
        vanguardflowtoken = vanguard_response.json()["vanguardflowtoken"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        log.error(
            "login_pwd: non-JSON checkpassword.srf status=%s for %s snippet=%r",
            vanguard_response.status_code,
            email,
            body[:400],
        )
        raise httpx.RemoteProtocolError(
            f"checkpassword.srf non-JSON response (status={vanguard_response.status_code})"
        ) from exc

    print(f"Got VanguardFlowtoken ({vanguardflowtoken})")
    password_post = await session.post(
        url=post_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "type": 11,
            "login": email,
            "loginfmt": email,
            "passwd": password,
            "PPFT": ppft,
            "vanguardflowtoken": vanguardflowtoken,
        },
        follow_redirects=True,
    )

    return password_post.text
