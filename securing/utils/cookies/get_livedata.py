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


async def livedata(session: httpx.AsyncClient) -> dict:
    """Fetch login.live.com urlPost + PPFT for subsequent login posts.

    Microsoft changes post.srf query params often (e.g. dropped ``pid=0``).
    Never call ``.group()`` on a failed match — that produced the useless
    ``AttributeError: 'NoneType' object has no attribute 'group'`` failures.
    """
    response = await session.post("https://login.live.com")
    html = response.text or ""

    url_post = _extract_url_post(html)
    ppft = _extract_ppft(html)

    if not url_post or not ppft:
        page_id = re.search(r'PageID" content="([^"]+)"', html)
        logging.error(
            "livedata parse failed status=%s page=%s urlPost=%s ppft=%s snippet=%s",
            response.status_code,
            page_id.group(1) if page_id else "?",
            bool(url_post),
            bool(ppft),
            html[:400].replace("\n", " "),
        )
        raise RuntimeError(
            "Failed to parse Microsoft login page (urlPost/PPFT missing). "
            f"PageID={page_id.group(1) if page_id else 'unknown'} — try again."
        )

    return {"urlPost": url_post, "ppft": ppft}
