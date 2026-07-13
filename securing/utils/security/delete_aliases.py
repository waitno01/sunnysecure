import logging
import re

import httpx

logger = logging.getLogger(__name__)

_CANARY_PATTERNS = (
    r'name="canary"\s+value="([^"]+)"',
    r'id="canary"[^>]*value="([^"]+)"',
    r'<input[^>]*name="canary"[^>]*value="([^"]+)"',
    r'"canary"\s*:\s*"([^"]+)"',
)


def _extract_canary(html: str) -> str | None:
    for pat in _CANARY_PATTERNS:
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1)
    return None


async def delete_aliases(session: httpx.AsyncClient) -> None:
    """Remove secondary aliases. Soft-skips if the manage page has no canary
    (common when Microsoft returns an interrupt / i5600 / SSO page instead).
    """
    response = await session.get(
        url="https://account.live.com/names/manage",
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        follow_redirects=True,
    )

    canary = _extract_canary(response.text or "")
    if not canary:
        page_id = re.search(r'PageID" content="([^"]+)"', response.text or "")
        logger.warning(
            "delete_aliases: no canary (status=%s page=%s url=%s len=%s) — skipping",
            response.status_code,
            page_id.group(1) if page_id else "?",
            str(response.url)[:120],
            len(response.text or ""),
        )
        print("[~] - Skipping alias removal (manage page missing canary)")
        return

    aliases = re.findall(
        r'id="idAliasEmail\d+".*?<span class="dirltr\s*">([^<]+@[^<]+)</span>',
        response.text,
        re.DOTALL,
    )

    if not aliases:
        print("[~] - No aliases to remove")
        return

    print(f"[~] - Found Aliases ({aliases})")
    for alias in aliases:
        await session.post(
            url="https://account.live.com/names/Manage",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            data={
                "canary": canary,
                "action": "RemoveAlias",
                "aliasName": alias,
                "displayName": alias,
            },
        )
        print(f"[+] - Removed {alias}")
