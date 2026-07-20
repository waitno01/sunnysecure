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


async def delete_aliases(
    session: httpx.AsyncClient,
    *,
    keep_email: str | None = None,
    security_email: str | None = None,
    account_email: str | None = None,
    password: str | None = None,
) -> None:
    """Remove secondary aliases. Soft-skips if the manage page has no canary
    (common when Microsoft returns an interrupt / i5600 / SSO page instead).

    ``keep_email`` — never remove this address (new primary / current login).
    When canary is missing and security_email is provided, try SA elevation once.
    """
    response = await session.get(
        url="https://account.live.com/names/manage",
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        follow_redirects=True,
    )

    text = response.text or ""
    canary = _extract_canary(text)
    if not canary and security_email:
        try:
            from securing.utils.security.change_primary_alias import (
                _elevate_for_names_manage,
            )

            print("[~] - Alias removal needs SA elevation — elevating…")
            text, canary, _emails = await _elevate_for_names_manage(
                session,
                text,
                security_email=security_email,
                account_email=account_email or keep_email,
                password=password,
            )
        except Exception as exc:
            logger.warning("delete_aliases elevate failed: %s", exc)

    if not canary:
        page_id = re.search(r'PageID" content="([^"]+)"', text or "")
        logger.warning(
            "delete_aliases: no canary (status=%s page=%s url=%s len=%s) — skipping",
            response.status_code,
            page_id.group(1) if page_id else "?",
            str(response.url)[:120],
            len(text or ""),
        )
        print("[~] - Skipping alias removal (manage page missing canary)")
        return

    aliases = re.findall(
        r'id="idAliasEmail\d+".*?<span class="dirltr\s*">([^<]+@[^<]+)</span>',
        text,
        re.DOTALL,
    )
    if not aliases:
        # Fallback scrape — manage page markup varies
        aliases = re.findall(
            r'([a-zA-Z0-9._+-]+@(?:outlook|hotmail|live|gmail)\.[a-zA-Z.]{2,})',
            text,
        )
        # de-dupe
        seen: set[str] = set()
        cleaned: list[str] = []
        for a in aliases:
            al = a.strip().lower()
            if al not in seen and "ilovevbucks" not in al:
                seen.add(al)
                cleaned.append(a.strip())
        aliases = cleaned

    if not aliases:
        print("[~] - No aliases to remove")
        return

    keep = (keep_email or "").strip().lower()
    keep_local = keep.split("@", 1)[0] if keep else ""

    print(f"[~] - Found Aliases ({aliases})")
    removed = 0
    for alias in aliases:
        alias_l = alias.strip().lower()
        local = alias_l.split("@", 1)[0]
        # Never delete the kept primary (or its local-part match)
        if keep and (alias_l == keep or (keep_local and local == keep_local)):
            print(f"[~] - Keeping primary alias ({alias})")
            continue
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
        removed += 1
    if removed:
        print(f"[+] - Removed {removed} foreign alias(es)")
