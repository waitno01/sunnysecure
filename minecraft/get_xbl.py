import base64
import json
import logging
import re

import httpx

from minecraft.retry import TransientMCError, with_retries

log = logging.getLogger(__name__)


async def _get_xbl_once(session: httpx.AsyncClient) -> dict | None:
    data = await session.get(
        url="https://sisu.xboxlive.com/connect/XboxLive/?state=login&cobrandId=8058f65d-ce06-4c30-9559-473c9275a65d&tid=896928775&ru=https://www.minecraft.net/en-us/login&aid=1142970254",
        follow_redirects=False,
    )

    if data.status_code in (429, 500, 502, 503, 504):
        raise TransientMCError(f"sisu connect status {data.status_code}", status=data.status_code)

    location = data.headers.get("Location")
    if not location:
        # Missing Location can be a transient auth race after login
        raise TransientMCError("sisu connect missing Location header")

    acessTokenRedirect = await session.get(url=location, follow_redirects=False)
    if acessTokenRedirect.status_code in (429, 500, 502, 503, 504):
        raise TransientMCError(
            f"sisu redirect1 status {acessTokenRedirect.status_code}",
            status=acessTokenRedirect.status_code,
        )

    location = acessTokenRedirect.headers.get("Location")
    if not location:
        raise TransientMCError("sisu redirect1 missing Location header")

    accessTokenRedirect = await session.get(url=location, follow_redirects=False)
    if accessTokenRedirect.status_code in (429, 500, 502, 503, 504):
        raise TransientMCError(
            f"sisu redirect2 status {accessTokenRedirect.status_code}",
            status=accessTokenRedirect.status_code,
        )

    location = accessTokenRedirect.headers.get("Location")
    if not location:
        raise TransientMCError("sisu redirect2 missing Location header")

    # https://www.minecraft.net/en-us/login#state=login&accessToken=<token>
    token = re.search(r"accessToken=([^&#]+)", location)
    if not token:
        # Often a false alarm right after login / overprotective skip
        raise TransientMCError("accessToken missing from minecraft.net redirect")

    accessToken = token.group(1) + "=" * ((4 - len(token.group(1)) % 4) % 4)
    decoded_data = base64.b64decode(accessToken).decode("utf-8")
    json_data = json.loads(decoded_data)
    uhs = json_data[0].get("Item2", {}).get("DisplayClaims", {}).get("xui", [{}])[0].get("uhs")

    xsts = ""
    gtg = None
    for item in json_data:
        if item.get("Item1") == "rp://api.minecraftservices.com/":
            xsts = item.get("Item2", {}).get("Token", "")
        elif item.get("Item1") == "http://xboxlive.com":
            xui = item.get("Item2", {}).get("DisplayClaims", {}).get("xui", [{}])[0]
            if xui:
                gtg = xui.get("gtg")

    if not uhs or not xsts:
        raise TransientMCError("decoded XBL token missing uhs/xsts")

    return {"xbl": f"XBL3.0 x={uhs};{xsts}", "gtg": gtg}


async def get_xbl(session: httpx.AsyncClient) -> dict | None:
    return await with_retries(
        "get_xbl",
        lambda: _get_xbl_once(session),
        attempts=3,
        base_delay=2.5,
        retry_on_none=False,
    )
