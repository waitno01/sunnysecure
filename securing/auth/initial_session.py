from fake_useragent import UserAgent
import httpx

from securing.utils.cookies.safe_cookies import dedupe_cookies
from securing.utils.proxy import build_proxy_url


def get_session() -> httpx.AsyncClient:
    # Persistent session that handles cookies automatically.
    # Response hook collapses duplicate MSCC/etc so httpx never raises CookieConflict.
    # Each call mints a fresh sticky proxy SSID (60m) when proxy is enabled.

    async def _dedupe_hook(response: httpx.Response) -> None:
        dedupe_cookies(client)

    proxy_url = build_proxy_url()
    kwargs: dict = {}
    if proxy_url:
        # httpx 0.28+ uses `proxy=`; older used `proxies=`
        kwargs["proxy"] = proxy_url

    # Never use timeout=None — polish/SSO GETs can hang forever with no logs.
    client = httpx.AsyncClient(
        headers={
            "User-Agent": UserAgent().random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        },
        timeout=httpx.Timeout(45.0, connect=20.0),
        cookies=httpx.Cookies(),
        event_hooks={"response": [_dedupe_hook]},
        **kwargs,
    )
    return client
