#!/usr/bin/env python3
"""Deep forensic dump of a scammer-supplied MSA before / during secure.

Goal: find EVERY planted pullback vector (proofs, aliases, devices, OAuth,
passkeys, family, phones, cookies/tokens, GetCredentialType flags).

Usage:
  .venv/bin/python scripts/forensic_pullback_dump.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("forensic")

EMAIL = "mcfa.uhtn6av7@outlook.com"
RC = "WR95F-A84GQ-HC7U5-WBBHX-R6V34"
OUT = Path(__file__).resolve().parents[1] / "forensics" / f"pullback_{EMAIL.split('@')[0]}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"

PROOF_KEYS = (
    "emailProofs",
    "smsProofs",
    "phoneProofs",
    "totpProofs",
    "appProofs",
    "passkeyProofs",
    "windowsHelloProofs",
    "alternateEmailProofs",
    "oProofList",
    "arrUserProofs",
)


def _jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    return str(obj)


def _extract_json_array(html: str, key: str) -> list | None:
    m = re.search(rf'"{re.escape(key)}"\s*:\s*', html or "")
    if not m:
        return None
    i = m.end()
    if i >= len(html) or html[i] != "[":
        return None
    depth = 0
    for j in range(i, len(html)):
        if html[j] == "[":
            depth += 1
        elif html[j] == "]":
            depth -= 1
            if depth == 0:
                raw = html[i : j + 1]
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    try:
                        data = json.loads(raw.encode().decode("unicode_escape"))
                    except Exception:
                        return None
                return data if isinstance(data, list) else [data]
    return None


def _extract_serverdata_blob(html: str) -> dict:
    """Best-effort ServerData / config extract from MS HTML."""
    out: dict[str, Any] = {}
    for key in PROOF_KEYS + (
        "sFT",
        "apiCanary",
        "canary",
        "sEncryptedNetId",
        "sNetId",
        "sPUID",
        "sCID",
        "sSigninName",
        "sUserEmail",
        "sPrimaryEmail",
        "fHasPhone",
        "fHasSkype",
        "fHasAuthenticator",
        "fIsTfaEnabled",
        "iMaxProofs",
        "oPostParams",
        "urlPost",
        "urlSwitch",
        "sFTTag",
        "iPassportFlags",
        "iProduct",
    ):
        arr = _extract_json_array(html, key)
        if arr is not None:
            out[key] = arr
            continue
        m = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', html or "")
        if m:
            try:
                out[key] = json.loads(f'"{m.group(1)}"')
            except Exception:
                out[key] = m.group(1)
            continue
        m = re.search(rf'"{re.escape(key)}"\s*:\s*(true|false|\d+)', html or "")
        if m:
            raw = m.group(1)
            out[key] = True if raw == "true" else False if raw == "false" else int(raw)
    # Alias list often in sAliasList / aliases
    for key in ("sAliasList", "aliases", "oNameList", "arrAliases"):
        arr = _extract_json_array(html, key)
        if arr is not None:
            out[key] = arr
    return out


def _cookie_dump(session) -> list[dict]:
    rows = []
    for c in session.cookies.jar:
        rows.append(
            {
                "name": c.name,
                "domain": c.domain,
                "path": c.path,
                "secure": bool(c.secure),
                "value_len": len(c.value or ""),
                "value_prefix": (c.value or "")[:24],
                # Full value only for non-auth cookies (safer + still useful)
                "value": None
                if c.name
                in (
                    "__Host-MSAAUTH",
                    "__Host-MSAAUTHP",
                    "MSPAuth",
                    "MSPProf",
                    "WLSSC",
                    "AMCSecAuth",
                    "AMCSecAuthJWT",
                )
                else (c.value or "")[:200],
            }
        )
    return rows


async def _get_text(session, url: str, **kw) -> tuple[int, str, str]:
    r = await session.get(url, follow_redirects=True, **kw)
    return r.status_code, str(r.url), r.text or ""


async def _get_json(session, url: str, headers: dict | None = None) -> Any:
    r = await session.get(url, headers=headers or {}, follow_redirects=True)
    try:
        return {"status": r.status_code, "url": str(r.url), "json": r.json()}
    except Exception:
        return {
            "status": r.status_code,
            "url": str(r.url),
            "text": (r.text or "")[:2000],
        }


async def main() -> None:
    from database.database import DBConnection
    from securing.auth.handle_redirects import get_data, handle_redirects
    from securing.auth.initial_session import get_session
    from securing.auth.polish_host import polish_host
    from securing.autobuy_hold_check import fetch_credential_type
    from securing.utils.cookies.get_amc import get_amc
    from securing.utils.cookies.get_livedata import livedata
    from securing.utils.cookies.safe_cookies import has_cookie
    from securing.utils.login_pwd import login_pwd
    from securing.utils.ogi.get_contacts import get_contacts
    from securing.utils.ogi.get_devices import get_devices
    from securing.utils.ogi.get_family import get_family
    from securing.utils.ogi.get_owner_info import get_owner_info
    from securing.utils.proxy import close_session
    from securing.utils.security.password_gen import generate_ms_password
    from securing.utils.security.recovery import (
        check_recovery_code_valid,
        recover,
    )
    from securing.utils.secure import secure

    report: dict[str, Any] = {
        "target": EMAIL,
        "rc_provided": RC,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "phases": {},
        "findings": [],
        "confidence_notes": [],
    }

    # ── Phase 0: read-only pre-recover intel ──────────────────────────
    print("\n========== PHASE 0: pre-recover read-only ==========")
    gct = await fetch_credential_type(EMAIL)
    report["phases"]["0_get_credential_type"] = _jsonable(gct)
    if isinstance(gct, dict):
        creds = gct.get("Credentials") or {}
        report["findings"].append(
            {
                "phase": 0,
                "HasPhone": creds.get("HasPhone"),
                "HasRemoteNGC": creds.get("HasRemoteNGC"),
                "PrefCredential": creds.get("PrefCredential"),
                "RemoteNgcParams": creds.get("RemoteNgcParams"),
                "FidoParams": creds.get("FidoParams"),
                "OtcLoginEligibleProofs": creds.get("OtcLoginEligibleProofs"),
                "Credentials_keys": list(creds.keys()) if isinstance(creds, dict) else None,
                "IfExistsResult": gct.get("IfExistsResult"),
                "ThrottleStatus": gct.get("ThrottleStatus"),
                "EstsProperties": gct.get("EstsProperties"),
            }
        )
        print("GetCredentialType Credentials keys:", list(creds.keys()) if isinstance(creds, dict) else None)
        print("HasPhone:", creds.get("HasPhone"))
        print("PrefCredential:", creds.get("PrefCredential"))
        print("OtcLoginEligibleProofs:", creds.get("OtcLoginEligibleProofs"))
        print("FidoParams:", creds.get("FidoParams"))
        print("RemoteNgcParams:", creds.get("RemoteNgcParams"))

    rc_check = await check_recovery_code_valid(EMAIL, RC)
    report["phases"]["0_verify_recovery_code"] = _jsonable(rc_check)
    print("RC readonly:", rc_check)

    # ── Phase 1: RecoverUser (take ownership) ─────────────────────────
    print("\n========== PHASE 1: RecoverUser ==========")
    domain = "ilovevbucks.site"
    try:
        with open("config/config.json") as f:
            domain = str(json.load(f).get("domain") or domain)
    except Exception:
        pass

    sec_email = f"{uuid.uuid4().hex[:16]}@{domain}"
    password = generate_ms_password(14)
    print(f"New security email: {sec_email}")
    print(f"New password: {password}")

    with DBConnection() as db:
        db.add_security_email(sec_email, password)

    session = get_session()
    try:
        new_rc = await recover(session, EMAIL, RC, sec_email, password)
        report["phases"]["1_recover"] = {
            "ok": bool(new_rc and new_rc != "invalid"),
            "new_rc": new_rc,
            "security_email": sec_email,
            "password": password,
        }
        print("RecoverUser result RC:", new_rc)
        if not new_rc or new_rc == "invalid":
            report["error"] = "RecoverUser failed"
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(report, indent=2))
            print("Wrote", OUT)
            return

        await close_session(session)

        # ── Phase 2: login with NEW password, dump EVERYTHING before wipe ──
        print("\n========== PHASE 2: login + forensic dump (pre-wipe) ==========")
        session = get_session()
        live = await livedata(session)
        page = await login_pwd(session, EMAIL, live["urlPost"], password, live["ppft"])
        report["phases"]["2_login_page_fingerprint"] = {
            "len": len(page or ""),
            "has_arrUserProofs": "arrUserProofs" in (page or ""),
            "has_passkey": "passkey" in (page or "").lower(),
            "has_incorrect": "incorrect" in (page or "").lower(),
            "snippet": (page or "")[:800],
            "serverdata": _extract_serverdata_blob(page or ""),
        }
        msa = get_data(page)
        if not msa:
            handled = await handle_redirects(session, page)
            if isinstance(handled, dict) and handled.get("urlPost"):
                msa = handled
            elif isinstance(handled, str):
                report["phases"]["2_after_redirect_serverdata"] = _extract_serverdata_blob(handled)
                msa = get_data(handled)
                page = handled
        if not msa or not msa.get("urlPost"):
            if has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth"):
                msa = {"_cookies_only": True}
            else:
                report["error"] = "login failed after recover"
                report["phases"]["2_login_fail_page"] = (page or "")[:3000]
                OUT.parent.mkdir(parents=True, exist_ok=True)
                OUT.write_text(json.dumps(report, indent=2))
                print("LOGIN FAIL — wrote", OUT)
                return

        await polish_host(session, msa)
        report["phases"]["2_cookies"] = _cookie_dump(session)
        print("Logged in. Cookies:", [c["name"] for c in report["phases"]["2_cookies"]])

        # Proofs manage pages (THE goldmine for planted proofs)
        proofs_dump: dict[str, Any] = {}
        for label, url in (
            ("manage_additional", "https://account.live.com/proofs/Manage/additional"),
            ("manage", "https://account.live.com/proofs/manage"),
            ("manage_additional_q", "https://account.live.com/proofs/manage/additional?mkt=EN-US"),
            ("security_info", "https://account.live.com/proofs/manage/additional?mkt=en-US&refd=account.microsoft.com"),
        ):
            status, final, text = await _get_text(session, url)
            sd = _extract_serverdata_blob(text)
            proofs_dump[label] = {
                "status": status,
                "url": final,
                "len": len(text),
                "serverdata": sd,
                "proof_arrays": {k: sd.get(k) for k in PROOF_KEYS if k in sd},
                "title": (re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S) or [None, ""])[1][:80],
                "snippet": text[:1500],
            }
            print(f"Proofs {label}: status={status} keys={list(sd.keys())[:15]}")
            for pk in PROOF_KEYS:
                if sd.get(pk):
                    print(f"  {pk}: {json.dumps(sd[pk], default=str)[:500]}")
        report["phases"]["2_proofs"] = proofs_dump

        # Names / aliases
        aliases_dump: dict[str, Any] = {}
        for label, url in (
            ("names_manage", "https://account.live.com/names/manage"),
            ("names_Manage", "https://account.live.com/names/Manage"),
        ):
            status, final, text = await _get_text(session, url)
            sd = _extract_serverdata_blob(text)
            # Also scrape visible emails
            emails = sorted(set(re.findall(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text, re.I)))
            aliases_dump[label] = {
                "status": status,
                "url": final,
                "len": len(text),
                "serverdata": sd,
                "emails_found": emails[:50],
                "snippet": text[:1500],
            }
            print(f"Aliases {label}: emails={emails[:20]}")
        report["phases"]["2_aliases"] = aliases_dump

        # OAuth consents
        status, final, text = await _get_text(
            session, "https://account.live.com/consent/Manage?guat=1"
        )
        client_ids = re.findall(r"client_id=([A-Fa-f0-9]{16})", text)
        app_names = re.findall(r'class="[^"]*consent[^"]*"[^>]*>([^<]+)<', text, re.I)
        report["phases"]["2_oauth_consents"] = {
            "status": status,
            "url": final,
            "client_ids": client_ids,
            "app_name_hints": app_names[:40],
            "len": len(text),
            "snippet": text[:2000],
        }
        print("OAuth client_ids:", client_ids)

        # App passwords page (often ignored by autosecure)
        for label, url in (
            ("app_passwords", "https://account.live.com/proofs/AppPassword"),
            ("app_passwords2", "https://account.live.com/proofs/manage/AppPassword"),
            ("client_apps", "https://account.live.com/consent/clientapps"),
        ):
            status, final, text = await _get_text(session, url)
            report["phases"].setdefault("2_app_passwords", {})[label] = {
                "status": status,
                "url": final,
                "len": len(text),
                "title": (re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S) or [None, ""])[1][:80],
                "has_password_list": "AppPassword" in text or "app password" in text.lower(),
                "snippet": text[:1200],
            }
            print(f"AppPwd {label}: status={status} url={final}")

        # Devices / family / contacts / owner via AMC
        try:
            tokens = await get_amc(session)
        except Exception as exc:
            log.exception("get_amc failed")
            tokens = {}
            report["phases"]["2_amc_error"] = str(exc)
        report["phases"]["2_amc_token_keys"] = list((tokens or {}).keys())

        home_tok = (tokens or {}).get("home")
        devices_tok = (tokens or {}).get("devices")
        profile_tok = (tokens or {}).get("profile")

        try:
            devices = await get_devices(session, devices_tok or home_tok)
        except Exception as exc:
            devices = {"error": str(exc)}
        try:
            family = await get_family(session, home_tok)
        except Exception as exc:
            family = {"error": str(exc)}
        try:
            contacts = await get_contacts(session, profile_tok or home_tok)
        except Exception as exc:
            contacts = {"error": str(exc)}
        try:
            owner = await get_owner_info(session, profile_tok or home_tok)
        except Exception as exc:
            owner = {"error": str(exc)}

        report["phases"]["2_devices"] = _jsonable(devices)
        report["phases"]["2_family"] = _jsonable(family)
        report["phases"]["2_contacts"] = _jsonable(contacts)
        report["phases"]["2_owner"] = _jsonable(owner)
        print("Devices:", json.dumps(devices, default=str)[:800])
        print("Family:", json.dumps(family, default=str)[:800])
        print("Contacts:", json.dumps(contacts, default=str)[:800])

        # Raw AMC endpoints
        raw_amc = {}
        for name, url, tok in (
            (
                "devices_summary",
                "https://account.microsoft.com/home/api/devices/devices-summary",
                devices_tok or home_tok,
            ),
            (
                "family_summary",
                "https://account.microsoft.com/home/api/family/family-summary",
                home_tok,
            ),
            (
                "personal_info",
                "https://account.microsoft.com/profile/api/v1/personal-info",
                profile_tok,
            ),
            (
                "contact_info",
                "https://account.microsoft.com/profile/api/v1/contact-info?includePhones=true&includeEmails=true",
                profile_tok,
            ),
            (
                "privacy_apps",
                "https://account.microsoft.com/privacy/api/apps-and-services",
                home_tok,
            ),
            (
                "signin_activity",
                "https://account.microsoft.com/security/api/signin-activity",
                home_tok,
            ),
            (
                "recent_activity",
                "https://account.microsoft.com/security/api/recent-activity",
                home_tok,
            ),
        ):
            headers = {
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
            }
            if tok:
                headers["__RequestVerificationToken"] = tok
            raw_amc[name] = await _get_json(session, url, headers)
            print(f"AMC {name}: status={raw_amc[name].get('status')}")
        report["phases"]["2_amc_raw"] = _jsonable(raw_amc)

        # Password / security options pages
        for label, url in (
            ("change_password", "https://account.live.com/password/Change"),
            ("security", "https://account.microsoft.com/security"),
            ("devices_page", "https://account.microsoft.com/devices"),
            ("family_page", "https://account.microsoft.com/family"),
            ("privacy", "https://account.microsoft.com/privacy/app-access"),
        ):
            status, final, text = await _get_text(session, url)
            report["phases"].setdefault("2_misc_pages", {})[label] = {
                "status": status,
                "url": final,
                "len": len(text),
                "title": (re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S) or [None, ""])[1][:100],
                "snippet": text[:1000],
            }

        # Post-recover GetCredentialType again (may show new security email)
        gct2 = await fetch_credential_type(EMAIL)
        report["phases"]["2_get_credential_type_after"] = _jsonable(gct2)
        if isinstance(gct2, dict):
            creds2 = gct2.get("Credentials") or {}
            print("Post-recover HasPhone:", creds2.get("HasPhone"))
            print("Post-recover OTC proofs:", creds2.get("OtcLoginEligibleProofs"))

        # ── Analyze findings ──
        planted = []
        # Collect all proofs across pages
        all_proofs = []
        for page_data in proofs_dump.values():
            for k, v in (page_data.get("proof_arrays") or {}).items():
                if v:
                    all_proofs.append({"array": k, "items": v})
                    planted.append({"type": "proof_array", "array": k, "count": len(v), "items": v})

        if client_ids:
            planted.append({"type": "oauth_consent", "client_ids": client_ids})

        alias_emails = []
        for a in aliases_dump.values():
            alias_emails.extend(a.get("emails_found") or [])
        alias_emails = sorted(set(alias_emails))
        foreign_aliases = [
            e
            for e in alias_emails
            if e.lower() != EMAIL.lower() and not e.lower().endswith(f"@{domain.lower()}")
        ]
        if foreign_aliases:
            planted.append({"type": "aliases", "emails": foreign_aliases})

        if isinstance(devices, dict) and (devices.get("devices") or devices.get("Devices")):
            planted.append({"type": "devices", "data": devices})
        if isinstance(family, dict) and (family.get("members") or family.get("Members")):
            planted.append({"type": "family", "data": family})

        if isinstance(gct, dict):
            c0 = gct.get("Credentials") or {}
            if c0.get("HasPhone"):
                planted.append({"type": "HasPhone_flag_pre", "value": c0.get("HasPhone")})
            if c0.get("FidoParams"):
                planted.append({"type": "FidoParams_pre", "value": c0.get("FidoParams")})
            if c0.get("RemoteNgcParams"):
                planted.append({"type": "RemoteNgc_pre", "value": c0.get("RemoteNgcParams")})

        report["planted_candidates"] = _jsonable(planted)

        # ── Phase 3: finish secure wipe ──
        print("\n========== PHASE 3: secure wipe ==========")
        account = {
            "microsoft": {
                "email": EMAIL,
                "original_email": EMAIL,
                "password": password,
                "security_email": sec_email,
                "recovery_code": new_rc,
            },
            "minecraft": {},
        }
        secured = await secure(
            session=session,
            recovery=False,
            account_info=account,
            command=True,
        )
        report["phases"]["3_secured_microsoft"] = _jsonable(
            (secured or {}).get("microsoft") if isinstance(secured, dict) else secured
        )
        print("Secure done. MS keys:", list(((secured or {}).get("microsoft") or {}).keys()))

        # Post-wipe dump
        status, final, text = await _get_text(
            session, "https://account.live.com/proofs/Manage/additional"
        )
        report["phases"]["3_proofs_after_wipe"] = {
            "status": status,
            "serverdata": _extract_serverdata_blob(text),
        }
        gct3 = await fetch_credential_type(
            ((secured or {}).get("microsoft") or {}).get("email") or EMAIL
        )
        report["phases"]["3_get_credential_type_final"] = _jsonable(gct3)

        # Persist secured account
        if isinstance(secured, dict) and (secured.get("microsoft") or {}).get("recovery_code"):
            account_id = uuid.uuid4().hex
            with DBConnection() as db:
                db.add_secured_account(account_id, secured)
            report["account_id"] = account_id
            ms = secured["microsoft"]
            print("\n=== SECURED CREDENTIALS ===")
            print("primary:", ms.get("email"))
            print("password:", ms.get("password"))
            print("security:", ms.get("security_email"))
            print("recovery:", ms.get("recovery_code"))
            print("auth:", ms.get("auth_secret"))

        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, indent=2, default=str))
        print("\nWrote full forensic report:", OUT)

        # Human summary
        print("\n========== PLANTED CANDIDATES SUMMARY ==========")
        for p in planted:
            print(json.dumps(p, default=str)[:600])
            print("---")

    finally:
        try:
            await close_session(session)
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
