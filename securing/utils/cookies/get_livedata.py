import codecs
import logging
import re

import httpx


def _extract_ppft(html: str) -> str | None:
    # Modern login pages embed PPFT inside JSON sFTTag (escaped HTML input).
    m = re.search(r'"sFTTag"\s*:\s*"((?:\\.|[^"\\])*)"', html)
    if m:
        try:
            tag = codecs.decode(m.group(1), "unicode_escape")
        except Exception:
            tag = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
        vm = re.search(r'value="([^"]+)"', tag)
        if vm:
            return vm.group(1)

    for pat in (
        r'name="PPFT"[^>]*value="([^"]+)"',
        r'id="i0327"[^>]*value="([^"]+)"',
        r'"sFT"\s*:\s*"([^"]+)"',
        r'name=\\"PPFT\\"[^>]*value=\\"([^\\"]+)\\"',
    ):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1)
    return None


def _extract_url_post(html: str) -> str | None:
    for pat in (
        r'"urlPost"\s*:\s*"(https://login\.live\.com/ppsecure/post\.srf[^"]+)"',
        r'"urlPost"\s*:\s*"(https://[^"]+post\.srf[^"]+)"',
        r'https://login\.live\.com/ppsecure/post\.srf\?[^\s"\'<>]+',
        r'action="(https://login\.live\.com/ppsecure/post\.srf[^"]*)"',
    ):
        m = re.search(pat, html)
        if m:
            return m.group(1) if m.lastindex else m.group(0)
    return None


def _clear_msa_login_cookies(session: httpx.AsyncClient) -> None:
    """Drop MSA auth cookies that make login.live.com return empty 302s."""
    names = (
        "__Host-MSAAUTH",
        "__Host-MSAAUTHP",
        "MSPAuth",
        "MSPProf",
        "MSPVis",
        "MSPPre",
        "MSPCID",
        "MSPBack",
        "NAP",
        "ANON",
        "WLSSC",
        "AMCSecAuth",
        "AMCSecAuthJWT",
    )
    for name in names:
        try:
            session.cookies.delete(name)
        except Exception:
            pass
        # httpx may scope cookies by domain — clear common hosts
        for domain in (".live.com", "login.live.com", ".login.live.com",
                       ".microsoft.com", "account.microsoft.com", ".account.microsoft.com"):
            try:
                session.cookies.delete(name, domain=domain)
            except Exception:
                pass


async def livedata(session: httpx.AsyncClient) -> dict:
    """Fetch login.live.com urlPost + PPFT for subsequent login posts.

    Microsoft changes post.srf query params often (e.g. dropped ``pid=0``).
    Never call ``.group()`` on a failed match — that produced the useless
    ``AttributeError: 'NoneType' object has no attribute 'group'`` failures.

    If the session is already authenticated, login.live.com returns an empty
    302 with no form — clear MSA cookies and retry once.
    """
    last_status = None
    last_html = ""

    for attempt in range(2):
        response = await session.post(
            "https://login.live.com",
            follow_redirects=True,
        )
        last_status = response.status_code
        last_html = response.text or ""

        url_post = _extract_url_post(last_html)
        ppft = _extract_ppft(last_html)
        if url_post and ppft:
            return {"urlPost": url_post, "ppft": ppft}

        # Already-signed-in sessions often get a blank/redirect page.
        if attempt == 0 and (
            last_status in (301, 302, 303)
            or not last_html.strip()
            or not url_post
            or not ppft
        ):
            logging.warning(
                "livedata: no login form (status=%s len=%s) — clearing MSA cookies and retrying",
                last_status,
                len(last_html),
            )
            _clear_msa_login_cookies(session)
            continue
        break

    page_id = re.search(r'PageID" content="([^"]+)"', last_html)
    logging.error(
        "livedata parse failed status=%s page=%s urlPost=%s ppft=%s snippet=%s",
        last_status,
        page_id.group(1) if page_id else "?",
        bool(_extract_url_post(last_html)),
        bool(_extract_ppft(last_html)),
        last_html[:400].replace("\n", " "),
    )
    raise RuntimeError(
        "Failed to parse Microsoft login page (urlPost/PPFT missing). "
        f"PageID={page_id.group(1) if page_id else 'unknown'} — try again."
    )
