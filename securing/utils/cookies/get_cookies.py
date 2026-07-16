import logging
import re
import urllib.parse

import httpx

log = logging.getLogger(__name__)


def _decode_canary(raw: str) -> str:
    return re.sub(
        r"\\u([0-9A-Fa-f]{4})",
        lambda m: chr(int(m.group(1), 16)),
        urllib.parse.unquote(raw),
    )


def _find_canary(html: str) -> str | None:
    if not html:
        return None
    for pat in (
        r'"apiCanary"\s*:\s*"((?:\\.|[^"\\])*)"',
        r'name="canary"[^>]*value="([^"]+)"',
        r'"canary"\s*:\s*"((?:\\.|[^"\\])*)"',
    ):
        m = re.search(pat, html, re.I)
        if m:
            try:
                return _decode_canary(json_unescape(m.group(1)))
            except Exception:
                return _decode_canary(m.group(1))
    return None


def json_unescape(raw: str) -> str:
    try:
        import json

        return json.loads(f'"{raw}"')
    except Exception:
        return raw.replace("\\/", "/").replace('\\"', '"')


async def get_cookies(session: httpx.AsyncClient) -> str | None:
    """Scrape apiCanary for SA elevation APIs.

    Returns None instead of crashing when password/reset has no canary
    (common on interrupt / already-elevated sessions).
    """
    urls = (
        "https://account.live.com/password/reset",
        "https://account.live.com/",
        "https://account.live.com/proofs/Manage/additional",
    )
    for url in urls:
        try:
            data = await session.get(
                url=url,
                headers={"host": "account.live.com"},
                follow_redirects=True,
            )
        except Exception:
            log.exception("get_cookies: GET %s failed", url)
            continue
        canary = _find_canary(data.text or "")
        if canary:
            return canary
        log.warning(
            "get_cookies: no canary on %s (status=%s len=%s)",
            url,
            data.status_code,
            len(data.text or ""),
        )
    return None
