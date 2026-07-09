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


def _session_ready(session: httpx.AsyncClient) -> bool:
    return (
        has_cookie(session, "AMCSecAuthJWT")
        or has_cookie(session, "WLSSC")
        or has_cookie(session, "MSPAuth")
        or has_cookie(session, "__Host-MSAAUTH")
        or has_cookie(session, "__Host-MSAAUTHP")
    )


def _is_msal_bridge(html: str) -> bool:
    return (
        "MSALBrowserBundleName" in html
        or "complete-client-signin-oauth" in html
        or "ssoSilent" in html
    )


async def polish_host(session: httpx.AsyncClient, post_data: dict) -> str:
    # Persist Microsoft session (WLSSC / AMCSecAuthJWT) for account.microsoft.com APIs.
    # Never block forever: MSAL JS bridge SSO GETs hang with timeout=None.

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
        return polish.text

    # KMSI / type=28 often already set session cookies. The MSAL bridge page only
    # works in a real browser (JS). Following its meta-refresh SSO URL with httpx
    # can hang indefinitely — that is the "stuck securing, no logs" bug.
    if _session_ready(session) and _is_msal_bridge(polish.text):
        print("[~] - Polish: MSAL bridge + session cookies present — skipping SSO GET")
        return polish.text

    if _session_ready(session) and not _extract_sso_redirect(polish.text):
        print("[~] - Polish: session cookies present, no SSO URL — done")
        return polish.text

    sso_redirect = _extract_sso_redirect(polish.text)
    if not sso_redirect:
        logging.warning("polish_host: no complete-sso-with-redirect URL in response")
        print("[!] - Polish: no SSO redirect URL found")
        return polish.text

    # If we already have AMC/WLSSC, SSO form is optional — don't risk a hang.
    if has_cookie(session, "AMCSecAuthJWT") or has_cookie(session, "WLSSC"):
        print("[~] - Polish: AMC/WLSSC already set — skipping SSO GET")
        return polish.text

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
        return polish.text

    action_m = re.search(r'action="([^"]+)"', auth.text)
    pprid_m = re.search(r'name="pprid"[^>]*value="([^"]+)"', auth.text)
    nap_m = re.search(r'name="NAP"[^>]*value="([^"]+)"', auth.text)
    anon_m = re.search(r'name="ANON"[^>]*value="([^"]+)"', auth.text)
    t_m = re.search(r'name="t"[^>]*value="([^"]+)"', auth.text)

    if not (action_m and pprid_m and nap_m and anon_m and t_m):
        logging.warning("polish_host: SSO page missing form fields")
        print("[!] - Polish: SSO page missing form fields")
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

    return auth.text
