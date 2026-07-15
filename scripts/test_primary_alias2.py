#!/usr/bin/env python3
"""Retest primary alias after i5600 elevation fix."""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from securing.auth.initial_session import get_session
from securing.utils.cookies.get_cookies import get_cookies
from securing.utils.cookies.get_livedata import livedata
from securing.utils.login_pwd import login_pwd
from securing.auth.handle_redirects import handle_redirects, get_data
from securing.auth.polish_host import polish_host
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.security.change_primary_alias import (
    change_primary_alias,
    _get_manage,
)

EMAIL = "amazing_fam.iyq28s64@outlook.com"
PASSWORD = "NZ6b0bbGHapxOFpv"
SEC_EMAIL = "1bdeb6166728@ilovevbucks.site"


async def main():
    session = get_session()
    live = await livedata(session)
    page = await login_pwd(session, EMAIL, live["urlPost"], PASSWORD, live["ppft"])
    msa = get_data(page)
    if not msa:
        handled = await handle_redirects(session, page)
        if isinstance(handled, dict) and handled.get("urlPost"):
            msa = handled
        elif isinstance(handled, str):
            msa = get_data(handled)
    if not msa or not msa.get("urlPost"):
        if has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth"):
            msa = {"_cookies_only": True}
        else:
            print("LOGIN FAIL")
            return
    await polish_host(session, msa)
    print("logged in")

    apicanary = await get_cookies(session)
    local = f"sunny{uuid.uuid4().hex[:12]}"
    print("trying", local)
    ok = await change_primary_alias(
        session,
        local,
        apicanary,
        security_email=SEC_EMAIL,
        account_email=EMAIL,
        password=PASSWORD,
    )
    print("RESULT", ok)
    _, canary, emails = await _get_manage(session)
    print("canary", bool(canary), "emails", emails)

    # Also print creds snapshot for the user
    print("\n=== CREDENTIALS ===")
    print("primary:", f"{local}@outlook.com" if ok else EMAIL)
    print("password:", PASSWORD)
    print("security:", SEC_EMAIL)
    print("(recovery unchanged in this probe — use full secure for new recovery)")


if __name__ == "__main__":
    asyncio.run(main())
