"""Establish AMCSecAuth / AMCSecAuthJWT for account.microsoft.com APIs.

Without these cookies, personal-info / subscriptions / devices all return 401
(``getPersonalInfoFailed`` / ``unauthorized``). Dona-fork runs a dedicated
amc + amcjwt hop after login; our polish was skipping SSO once MSAAUTH existed.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import httpx

from securing.utils.cookies.safe_cookies import has_cookie

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(25.0, connect=10.0)


def has_amc_api_cookies(session: httpx.AsyncClient) -> bool:
    return has_cookie(session, "AMCSecAuthJWT") or has_cookie(session, "AMCSecAuth")


async def ensure_amc_jwt(session: httpx.AsyncClient) -> bool:
    """Best-effort: walk account.microsoft.com OAuth until AMC JWT is set.

    Mirrors dona ``tokens/amcjwt.py`` + ``tokens/amc.py`` silent-signin.
    Returns True when an AMC API cookie is present afterwards.
    """
    if has_amc_api_cookies(session):
        return True

    try:
        # --- amcjwt-style redirect chase (no JS) ---
        resp = await session.get(
            "https://account.microsoft.com/",
            follow_redirects=False,
            timeout=_TIMEOUT,
        )
        for hop in range(6):
            loc = resp.headers.get("location")
            if not loc:
                break
            if not loc.startswith("http"):
                loc = urljoin(str(resp.url), loc)
            log.info("ensure_amc_jwt hop %s → %s", hop, loc[:180])
            resp = await session.get(loc, follow_redirects=False, timeout=_TIMEOUT)
            if has_amc_api_cookies(session):
                print("[+] - AMCSecAuthJWT established (redirect chase)")
                return True
            # Sometimes the final hop is 200 with Set-Cookie
            if resp.status_code in (200, 302, 303) and has_amc_api_cookies(session):
                return True

        # Follow redirects fully once more (oauth complete pages)
        resp = await session.get(
            "https://account.microsoft.com/",
            follow_redirects=True,
            timeout=_TIMEOUT,
        )
        if has_amc_api_cookies(session):
            print("[+] - AMCSecAuthJWT established (full redirect)")
            return True

        # --- amc-style silent signin with ``t`` token ---
        resp = await session.get(
            "https://account.microsoft.com/",
            follow_redirects=False,
            timeout=_TIMEOUT,
        )
        loc = resp.headers.get("location")
        if loc:
            if not loc.startswith("http"):
                loc = urljoin(str(resp.url), loc)
            step2 = await session.get(loc, follow_redirects=True, timeout=_TIMEOUT)
            text = step2.text or ""
            t_m = re.search(
                r'<input[^>]*name="t"[^>]*value="([^"]+)"',
                text,
                re.I,
            ) or re.search(
                r'<input[^>]*id="t"[^>]*value="([^"]+)"',
                text,
                re.I,
            )
            if t_m:
                # Match dona tokens/amc.py nested complete-silent-signin ru=
                post_urls = (
                    (
                        "https://account.microsoft.com/auth/complete-silent-signin"
                        "?ru=https://account.microsoft.com/"
                        "auth/complete-silent-signin?ru=https%3A%2F%2Faccount.microsoft.com%2F"
                        "&wa=wsignin1.0&refd=login.live.com&wa=wsignin1.0"
                    ),
                    (
                        "https://account.microsoft.com/auth/complete-silent-signin"
                        "?ru=https://account.microsoft.com/"
                        "&wa=wsignin1.0&refd=login.live.com"
                    ),
                )
                for post_url in post_urls:
                    await session.post(
                        post_url,
                        data={"t": t_m.group(1)},
                        headers={"X-Requested-With": "XMLHttpRequest"},
                        follow_redirects=True,
                        timeout=_TIMEOUT,
                    )
                    if has_amc_api_cookies(session):
                        print("[+] - AMCSecAuth established (silent signin)")
                        return True

        # Last resort: hit profile which often finishes oauth
        await session.get(
            "https://account.microsoft.com/profile?lang=en-US",
            follow_redirects=True,
            timeout=_TIMEOUT,
        )
        if has_amc_api_cookies(session):
            print("[+] - AMCSecAuthJWT established (profile hop)")
            return True

    except (httpx.TimeoutException, httpx.TransportError) as exc:
        log.warning("ensure_amc_jwt transport error: %s", exc)
        print(f"[!] - ensure_amc_jwt failed ({exc.__class__.__name__})")
    except Exception:
        log.exception("ensure_amc_jwt crashed")

    ok = has_amc_api_cookies(session)
    if not ok:
        print("[!] - No AMCSecAuthJWT — account.microsoft.com APIs will 401")
    return ok
