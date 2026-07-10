import logging
import re

import httpx


async def get_t(session: httpx.AsyncClient) -> str | None:
    """Scrape the login ``t`` token used by get_amrp / proofs Add handshake.

    Microsoft often serves PageID i5600 (interrupt) instead of the classic
    hidden ``t`` input when the session is already signed in. In that case we
    try alternate field names / sFT, then return None so callers can soft-skip.
    """
    url = (
        "https://login.live.com/login.srf?wa=wsignin1.0&rpsnv=21"
        "&ct=1708978285&rver=7.5.2211.0&wp=SA_20MIN"
        "&wreply=https%3a%2f%2faccount.live.com%2fproofs%2fAdd%3fapt%3d2"
        "&lc=1033&id=38936&mkt=en-US"
    )

    fetchT = await session.get(url, follow_redirects=False)
    html = fetchT.text or ""

    patterns = (
        r'<input\s+type="hidden"\s+name="t"\s+id="t"\s+value="([^"]+)"\s*/?>',
        r'name="t"[^>]*value="([^"]+)"',
        r'id="t"[^>]*value="([^"]+)"',
        r'value="([^"]+)"[^>]*name="t"',
        r'name=\\"t\\"[^>]*value=\\"([^\\"]+)\\"',
        # Classic compact token still used by some flows
        r'value="(GAA[A-Za-z0-9+/=]{40,})"',
    )
    for pat in patterns:
        match = re.search(pat, html, re.I)
        if match:
            return match.group(1)

    # Already-authed interrupt page (i5600): may only expose sFT / PPFT.
    # That is not the classic ``t`` token — return None for soft-skip.
    page_id = re.search(r'PageID" content="([^"]+)"', html)
    sft = re.search(r'"sFT"\s*:\s*"([^"]+)"', html)
    logging.warning(
        "get_t: no classic t token (status=%s page=%s sFT=%s len=%s)",
        fetchT.status_code,
        page_id.group(1) if page_id else "?",
        bool(sft),
        len(html),
    )
    return None
