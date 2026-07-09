from fake_useragent import UserAgent
import httpx

from securing.utils.cookies.safe_cookies import dedupe_cookies


def get_session() -> httpx.AsyncClient:
    # Persistent session that handles cookies automatically.
    # Response hook collapses duplicate MSCC/etc so httpx never raises CookieConflict.

    async def _dedupe_hook(response: httpx.Response) -> None:
        dedupe_cookies(client)

    # Never use timeout=None — polish/SSO GETs can hang forever with no logs.
    client = httpx.AsyncClient(
        headers={
            "User-Agent": UserAgent().random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        },
        timeout=httpx.Timeout(30.0, connect=10.0),
        cookies=httpx.Cookies(),
        event_hooks={"response": [_dedupe_hook]},
    )
    return client
