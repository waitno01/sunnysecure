#!/usr/bin/env python3
"""Follow-up probe on mcfa account after partial secure — confirm planted vectors."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from securing.auth.handle_redirects import get_data, handle_redirects
from securing.auth.initial_session import get_session
from securing.auth.polish_host import polish_host
from securing.autobuy_hold_check import fetch_credential_type
from securing.utils.cookies.get_livedata import livedata
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.login_pwd import login_pwd
from securing.utils.proxy import close_session
from securing.utils.security.remove_zyger import remove_zyger
from securing.utils.security_information import security_information

EMAIL = "mcfa.uhtn6av7@outlook.com"
PWD = "FjU3K9ZG7LuxCg"
SEC = "0c33a830a1754f1f@ilovevbucks.site"
RC = "5KVF4-PVN82-38UM4-VKJ6N-N5PDS"
OUT = Path(__file__).resolve().parents[1] / "forensics" / "mcfa_followup.json"


def extract_arr_proofs(html: str):
    m = re.search(r'"arrUserProofs"\s*:\s*(\[.*?\])\s*,\s*"', html or "", re.S)
    if not m:
        m = re.search(r'"arrUserProofs"\s*:\s*(\[.*?\])', html or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        try:
            return json.loads(m.group(1).encode().decode("unicode_escape"))
        except Exception:
            return m.group(1)[:2000]


async def main():
    report = {"email": EMAIL, "checks": {}}

    print("=== GetCredentialType ===")
    gct = await fetch_credential_type(EMAIL)
    creds = (gct or {}).get("Credentials") or {}
    report["checks"]["gct"] = {
        "HasPhone": creds.get("HasPhone"),
        "HasFido": creds.get("HasFido"),
        "HasRemoteNGC": creds.get("HasRemoteNGC"),
        "PrefCredential": creds.get("PrefCredential"),
        "OtcLoginEligibleProofs": creds.get("OtcLoginEligibleProofs"),
        "FidoParams": creds.get("FidoParams"),
        "RemoteNgcParams": creds.get("RemoteNgcParams"),
        "all_keys": list(creds.keys()),
    }
    print(json.dumps(report["checks"]["gct"], indent=2, default=str))

    session = get_session()
    try:
        live = await livedata(session)
        page = await login_pwd(session, EMAIL, live["urlPost"], PWD, live["ppft"])
        msa = get_data(page)
        if not msa:
            h = await handle_redirects(session, page)
            if isinstance(h, dict):
                msa = h
            elif isinstance(h, str):
                report["checks"]["post_pwd_proofs"] = extract_arr_proofs(h)
                print("Post-password arrUserProofs:", report["checks"]["post_pwd_proofs"])
                msa = get_data(h)
                page = h
        # Capture passkey interrupt evidence
        report["checks"]["login_had_passkey_interrupt"] = "interrupt/passkey" in (page or "")
        report["checks"]["login_arrUserProofs"] = extract_arr_proofs(page or "")
        print("passkey interrupt:", report["checks"]["login_had_passkey_interrupt"])
        print("login proofs:", report["checks"]["login_arrUserProofs"])

        if not msa or not msa.get("urlPost"):
            if has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth"):
                msa = {"_cookies_only": True}
            else:
                print("LOGIN FAIL")
                OUT.parent.mkdir(parents=True, exist_ok=True)
                OUT.write_text(json.dumps(report, indent=2, default=str))
                return
        await polish_host(session, msa)

        # Elevate + scrape proofs manage
        print("=== security_information / proofs ===")
        try:
            info = await security_information(session, SEC, EMAIL, password=PWD)
            report["checks"]["security_information"] = {
                "ok": info is not None and info != "invalid",
                "type": type(info).__name__,
                "keys": list(info.keys()) if isinstance(info, dict) else None,
                "data": info if isinstance(info, dict) else str(info)[:500],
            }
            print("security_information:", report["checks"]["security_information"]["keys"])
        except Exception as exc:
            report["checks"]["security_information_error"] = repr(exc)
            print("SI error", exc)

        for url in (
            "https://account.live.com/proofs/Manage/additional",
            "https://account.live.com/proofs/manage",
            "https://account.live.com/names/manage",
            "https://account.live.com/consent/Manage?guat=1",
        ):
            r = await session.get(url, follow_redirects=True)
            text = r.text or ""
            proofs = extract_arr_proofs(text)
            emails = sorted(set(re.findall(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text, re.I)))
            # Also look for masked freakyward
            freaky = re.findall(r"freakyward\.cyou|zp\*+|@freaky", text, re.I)
            fido = re.findall(r"passkey|fido|windows.?hello|zyger|authenticator", text, re.I)
            report["checks"][url] = {
                "status": r.status_code,
                "final": str(r.url),
                "len": len(text),
                "arrUserProofs": proofs,
                "emails": emails[:30],
                "freaky_hits": freaky[:20],
                "fido_hits": list({x.lower() for x in fido})[:30],
                "title": (re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S) or [None, ""])[1][:80],
            }
            print(url, "proofs=", proofs, "freaky=", freaky[:5], "emails=", emails[:10])

        # Try revoke zyger again and capture FULL body
        # Need canary from a manage page
        r = await session.get("https://account.live.com/proofs/Manage/additional", follow_redirects=True)
        canary_m = re.search(r'"apiCanary"\s*:\s*"((?:\\.|[^"\\])*)"', r.text or "")
        canary = None
        if canary_m:
            canary = json.loads(f'"{canary_m.group(1)}"')
        report["checks"]["canary_present"] = bool(canary)
        if canary:
            rem = await session.post(
                "https://account.live.com/API/Proofs/RevokeWindowsHelloProofs",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "canary": canary,
                },
                json={
                    "uiflvr": 1001,
                    "uaid": "abd2ca2a346c43c198c9ca7e4255f3bc",
                    "scid": 100109,
                    "hpgid": 201030,
                },
            )
            report["checks"]["revoke_hello"] = {
                "status": rem.status_code,
                "body": (rem.text or "")[:1000],
            }
            print("RevokeWindowsHello:", rem.status_code, rem.text[:300])

            # List + delete any proof ids we can find
            # Also try DeleteProof for common patterns after scraping ServerData arrays
            for key in (
                "emailProofs",
                "smsProofs",
                "phoneProofs",
                "totpProofs",
                "appProofs",
                "passkeyProofs",
                "windowsHelloProofs",
                "alternateEmailProofs",
            ):
                m = re.search(rf'"{key}"\s*:\s*', r.text or "")
                if m:
                    report["checks"].setdefault("proof_key_hits", []).append(key)

        # Final GCT
        gct2 = await fetch_credential_type(EMAIL)
        c2 = (gct2 or {}).get("Credentials") or {}
        report["checks"]["gct_after"] = {
            "HasPhone": c2.get("HasPhone"),
            "HasFido": c2.get("HasFido"),
            "HasRemoteNGC": c2.get("HasRemoteNGC"),
            "OtcLoginEligibleProofs": c2.get("OtcLoginEligibleProofs"),
        }
        print("GCT after:", json.dumps(report["checks"]["gct_after"], indent=2, default=str))

    finally:
        await close_session(session)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print("Wrote", OUT)


if __name__ == "__main__":
    asyncio.run(main())
