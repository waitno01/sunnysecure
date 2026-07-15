import logging
import re

import httpx

_AMC_TIMEOUT = httpx.Timeout(25.0, connect=10.0)

# Home, Profile and Devices
endpoints = [
    "https://account.microsoft.com/profile?lang=en-US",
    "https://account.microsoft.com/profile/about?ru=https%3A%2F%2Faccount.microsoft.com%2Fprofile",
    "https://account.microsoft.com/devices/",
]


async def scrape_token(session: httpx.AsyncClient, url: str) -> str | None:
    response = await session.get(
        url=url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        },
        follow_redirects=True,
        timeout=_AMC_TIMEOUT,
    )

    logging.info("URL %s RESPONSE status=%s len=%s", url, response.status_code, len(response.text))
    token = re.search(
        r'name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]+)"',
        response.text,
        re.DOTALL,
    )
    if not token:
        logging.warning("get_amc: no RequestVerificationToken on %s (url=%s)", url, response.url)
        return None
    return token.group(1)


async def get_amc(session: httpx.AsyncClient) -> dict:
    # Gets AMCSecAuthJWT and scrapes RequestVerificationTokens per page.
    from securing.utils.cookies.ensure_amc_jwt import ensure_amc_jwt

    await ensure_amc_jwt(session)

    try:
        response = await session.get(
            "https://account.microsoft.com",
            follow_redirects=True,
            timeout=_AMC_TIMEOUT,
        )
        logging.info("Account home status=%s url=%s", response.status_code, response.url)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logging.warning("get_amc: account.microsoft.com failed: %s", exc)
        print(f"[!] - get_amc home failed ({exc.__class__.__name__})")

    home_token = await scrape_token(session, endpoints[0])
    profile_token = await scrape_token(session, endpoints[1])
    devices_token = await scrape_token(session, endpoints[2])

    if not home_token or not profile_token:
        # One more JWT bootstrap + retry scrape
        await ensure_amc_jwt(session)
        home_token = home_token or await scrape_token(session, endpoints[0])
        profile_token = profile_token or await scrape_token(session, endpoints[1])
        devices_token = devices_token or await scrape_token(session, endpoints[2])

    if not home_token or not profile_token:
        raise RuntimeError(
            "Failed to scrape RequestVerificationTokens — session may be incomplete after polish."
        )

    print(f"[+] - Got RequestVerificationTokens ({[home_token, profile_token, devices_token]})")
    return {
        "home": home_token,
        "profile": profile_token,
        "devices": devices_token or home_token,
    }
