import logging
import re

import httpx

from securing.utils.cookies.safe_cookies import has_cookie

# MSAL bridge / SSO pages can stall forever when timeout=None.
_POLISH_TIMEOUT = httpx.Timeout(25.0, connect=10.0)


def _extract_sso_redirect(html: str) -> str | None:
    """Pull complete-sso-with-redirect URL from polish / MSAL bridge HTML."""
    patterns = (
        r'https://account\.microsoft\.com/auth/complete-sso-with-redirect\?state=[A-Za-z0-9_\-+/=]+',
        r'content="\d+;(https://account\.microsoft\.com/auth/complete-sso-with-redirect\?state=[A-Za-z0-9_\-+/=]+)"',
        r'location\.replace\("(https://account\.microsoft\.com/auth/complete-sso-with-redirect\?state=[A-Za-z0-9_\-+/=]+)"\)',
        r'window\.location\.replace\("(https://account\.microsoft\.com/auth/complete-sso-with-redirect\?state=[A-Za-z0-9_\-+/=]+)"\)',
    )
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return m.group(1) if m.lastindex else m.group(0)
    return None


def _login_cookies_present(session: httpx.AsyncClient) -> bool:
    """True when MSA login cookies exist (NOT enough for account.microsoft.com APIs)."""
    return (
        has_cookie(session, "MSPAuth")
        or has_cookie(session, "__Host-MSAAUTH")
        or has_cookie(session, "__Host-MSAAUTHP")
        or has_cookie(session, "WLSSC")
    )


def _amc_api_ready(session: httpx.AsyncClient) -> bool:
    """True when account.microsoft.com profile/billing APIs can authorize."""
    return has_cookie(session, "AMCSecAuthJWT") or has_cookie(session, "AMCSecAuth")


def _amc_home_ready(session: httpx.AsyncClient) -> bool:
    """Home APIs (devices/family) need AMCSecAuth — JWT alone still 401s them."""
    return has_cookie(session, "AMCSecAuth")


def _session_ready(session: httpx.AsyncClient) -> bool:
    # Kept for callers; prefer _amc_api_ready when deciding to skip AMC SSO.
    return _amc_api_ready(session) or _login_cookies_present(session)


def _is_msal_bridge(html: str) -> bool:
    return (
        "MSALBrowserBundleName" in html
        or "complete-client-signin-oauth" in html
        or "ssoSilent" in html
    )


async def polish_host(session: httpx.AsyncClient, post_data: dict) -> str:
    # Persist Microsoft session (WLSSC / AMCSecAuthJWT) for account.microsoft.com APIs.
    # Never block forever: MSAL JS bridge SSO GETs hang with timeout=None.
    from securing.utils.cookies.ensure_amc_jwt import ensure_amc_jwt

    if post_data.get("_cookies_only"):
        print("[~] - Polish: cookies-only path (MSAAUTH already present)")
        logging.info("polish_host: cookies-only — hitting account portals for AMC/WLSSC")
        for portal in (
            "https://account.live.com/",
            "https://account.microsoft.com/",
        ):
            try:
                resp = await session.get(
                    portal,
                    follow_redirects=True,
                    timeout=_POLISH_TIMEOUT,
                )
                logging.info(
                    "polish_host cookies-only %s → status=%s url=%s",
                    portal,
                    resp.status_code,
                    resp.url,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                logging.warning("polish_host cookies-only %s failed: %s", portal, exc)
        await ensure_amc_jwt(session)
        return ""

    polish = await session.post(
        url=post_data["urlPost"],
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7"
            ),
        },
        data=f"PPFT={post_data['ppft']}&canary=&LoginOptions=3&type=28&hpgrequestid=&ctx=",
        follow_redirects=True,
        timeout=_POLISH_TIMEOUT,
    )

    logging.info("Polish Host Response: %s", polish.text[:2000])
    print(f"[+] - Polish Host Response: {polish.text[:500]}")

    if 'PageID" content="BssoInterrupt"' in polish.text or "BssoInterrupt" in polish.text:
        logging.info("polish_host: BssoInterrupt — skipping SSO form finish")
        print("[~] - Polish hit BssoInterrupt; relying on existing session cookies")
        await ensure_amc_jwt(session)
        return polish.text

    # JWT alone is enough for MSADELEGATE + owner-info fallback, but home APIs
    # (devices/family) need AMCSecAuth from the SSO form finish. Only skip the
    # MSAL SSO GET when AMCSecAuth is already present.
    if _amc_home_ready(session) and _is_msal_bridge(polish.text):
        print("[~] - Polish: MSAL bridge + AMCSecAuth present — skipping SSO GET")
        return polish.text

    if _amc_home_ready(session) and not _extract_sso_redirect(polish.text):
        print("[~] - Polish: AMCSecAuth present, no SSO URL — done")
        return polish.text

    sso_redirect = _extract_sso_redirect(polish.text)
    if not sso_redirect:
        logging.warning("polish_host: no complete-sso-with-redirect URL in response")
        print("[!] - Polish: no SSO redirect URL found — bootstrapping AMC JWT")
        await ensure_amc_jwt(session)
        return polish.text

    # If we already have AMCSecAuth, SSO form is optional — don't risk a hang.
    if _amc_home_ready(session):
        print("[~] - Polish: AMCSecAuth already set — skipping SSO GET")
        return polish.text

    if _amc_api_ready(session) and not _amc_home_ready(session):
        print("[~] - Polish: have AMC JWT but not AMCSecAuth — finishing SSO for home APIs")
    else:
        print("[~] - Polish: following SSO redirect…")
    try:
        auth = await session.get(
            url=sso_redirect,
            follow_redirects=True,
            timeout=_POLISH_TIMEOUT,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logging.warning("polish_host: SSO GET failed (%s) — continuing with cookies", exc)
        print(f"[!] - Polish SSO GET failed ({exc.__class__.__name__}); continuing")
        await ensure_amc_jwt(session)
        return polish.text

    action_m = re.search(r'action="([^"]+)"', auth.text)
    pprid_m = re.search(r'name="pprid"[^>]*value="([^"]+)"', auth.text)
    nap_m = re.search(r'name="NAP"[^>]*value="([^"]+)"', auth.text)
    anon_m = re.search(r'name="ANON"[^>]*value="([^"]+)"', auth.text)
    t_m = re.search(r'name="t"[^>]*value="([^"]+)"', auth.text)

    if not (action_m and pprid_m and nap_m and anon_m and t_m):
        logging.warning("polish_host: SSO page missing form fields")
        print("[!] - Polish: SSO page missing form fields — bootstrapping AMC JWT")
        await ensure_amc_jwt(session)
        return auth.text

    try:
        await session.post(
            url=action_m.group(1),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "pprid": pprid_m.group(1),
                "NAP": nap_m.group(1),
                "ANON": anon_m.group(1),
                "t": t_m.group(1),
            },
            follow_redirects=True,
            timeout=_POLISH_TIMEOUT,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logging.warning("polish_host: SSO form post failed (%s)", exc)
        print(f"[!] - Polish SSO form post failed ({exc.__class__.__name__})")

    if not _amc_api_ready(session):
        await ensure_amc_jwt(session)

    return auth.text
