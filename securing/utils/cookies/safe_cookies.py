"""Helpers that avoid httpx CookieConflict on duplicate cookie names (e.g. MSCC)."""

from __future__ import annotations

import httpx

# Names Microsoft commonly duplicates across login.live.com / account.live.com / .live.com
CONFLICT_NAMES = frozenset({"MSCC", "MSPOK", "PPLState", "uaid", "MSPRequ", "OParams"})


def iter_cookies(session: httpx.AsyncClient):
    return list(session.cookies.jar)


def has_cookie(session: httpx.AsyncClient, name: str) -> bool:
    return any(c.name == name for c in iter_cookies(session))


def get_cookie(session: httpx.AsyncClient, name: str) -> str | None:
    """Return the most recently set cookie value for name (last wins)."""
    value = None
    for c in iter_cookies(session):
        if c.name == name:
            value = c.value
    return value


def cookies_as_dict(session: httpx.AsyncClient) -> dict[str, str]:
    """Flatten cookies to name->value without raising CookieConflict."""
    out: dict[str, str] = {}
    for c in iter_cookies(session):
        out[c.name] = c.value
    return out


def dedupe_cookies(session: httpx.AsyncClient) -> None:
    """Collapse duplicate cookie names so httpx mapping ops never raise CookieConflict.

    Microsoft often sets MSCC (and friends) for both host and parent domain.
    httpx.Cookies.get / dict(cookies) then raise CookieConflict.
    """
    jar = session.cookies.jar
    # Keep last cookie per exact (name, domain, path)
    seen: dict[tuple[str, str, str], object] = {}
    for cookie in list(jar):
        key = (cookie.name, cookie.domain or "", cookie.path or "/")
        if key in seen:
            try:
                jar.clear(cookie.domain, cookie.path, cookie.name)
            except Exception:
                pass
        seen[key] = cookie

    # Collapse conflict-prone names to a single entry (last wins)
    latest: dict[str, object] = {}
    for cookie in list(jar):
        if cookie.name in CONFLICT_NAMES:
            latest[cookie.name] = cookie

    for cookie in list(jar):
        if cookie.name not in CONFLICT_NAMES:
            continue
        keep = latest.get(cookie.name)
        if keep is None or cookie is keep:
            continue
        try:
            jar.clear(cookie.domain, cookie.path, cookie.name)
        except Exception:
            pass


def install_cookie_dedupe_hook(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """Auto-dedupe the jar after every response so conflicts never accumulate."""

    async def _hook(response: httpx.Response) -> None:
        dedupe_cookies(client)

    client.event_hooks.setdefault("response", []).append(_hook)
    return client
