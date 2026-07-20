#!/usr/bin/env python3
"""Fetch account.live.com/Activity with a fully polished MSA session."""
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
from securing.utils.cookies.get_amc import get_amc
from securing.utils.cookies.get_livedata import livedata
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.login_pwd import login_pwd
from securing.utils.proxy import close_session

EMAIL = "mcfa.uhtn6av7@outlook.com"
PWD = "FjU3K9ZG7LuxCg"
OUT_DIR = Path(__file__).resolve().parents[1] / "forensics"


def _extract_activities(html: str) -> list[dict]:
    """Best-effort parse of Activity page event cards / JSON."""
    events: list[dict] = []

    # JSON islands commonly embedded in the page
    for pat in (
        r'"Activities"\s*:\s*(\[[\s\S]*?\])\s*,\s*"',
        r'"activities"\s*:\s*(\[[\s\S]*?\])\s*,\s*"',
        r'"activityList"\s*:\s*(\[[\s\S]*?\])',
        r'"RecentActivity"\s*:\s*(\[[\s\S]*?\])',
        r'"UnusualActivity"\s*:\s*(\[[\s\S]*?\])',
    ):
        m = re.search(pat, html or "")
        if not m:
            continue
        raw = m.group(1)
        # balance brackets if truncated greedily wrong
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        events.append(item)
        except json.JSONDecodeError:
            # try progressive trim
            for end in range(len(raw), 2, -1):
                if raw[end - 1] != "]":
                    continue
                try:
                    data = json.loads(raw[:end])
                    if isinstance(data, list):
                        events.extend([x for x in data if isinstance(x, dict)])
                        break
                except json.JSONDecodeError:
                    continue

    # HTML card fallbacks
    # Look for date + description patterns
    cards = re.findall(
        r'(?:class="[^"]*activity[^"]*"[^>]*>)([\s\S]{20,800}?)(?:</(?:div|li|article)>)',
        html or "",
        re.I,
    )
    text_events = []
    for card in cards[:50]:
        clean = re.sub(r"<[^>]+>", " ", card)
        clean = re.sub(r"\s+", " ", clean).strip()
        if len(clean) > 20:
            text_events.append(clean[:300])

    # Also pull ServerData-like key fields mentioning Location / IP / Date
    for m in re.finditer(
        r'"(?:Date|date|Location|location|IP|IpAddress|ipAddress|Platform|platform|Browser|browser|ActivityType|activityType|Description|description|Title|title)"\s*:\s*"((?:\\.|[^"\\])*)"',
        html or "",
    ):
        pass  # collected via JSON above

    return events, text_events


async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {"email": EMAIL, "pages": {}}

    session = get_session()
    try:
        live = await livedata(session)
        page = await login_pwd(session, EMAIL, live["urlPost"], PWD, live["ppft"])
        msa = get_data(page)
        if not msa:
            h = await handle_redirects(session, page)
            if isinstance(h, dict) and h.get("urlPost"):
                msa = h
            elif isinstance(h, str):
                msa = get_data(h)
        if not msa or not msa.get("urlPost"):
            if has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth"):
                msa = {"_cookies_only": True}
            else:
                print("LOGIN FAIL")
                return

        await polish_host(session, msa)
        try:
            tokens = await get_amc(session)
            print("AMC tokens:", {k: bool(v) for k, v in (tokens or {}).items()})
        except Exception as exc:
            print("get_amc:", exc)
            tokens = {}

        print(
            "cookies:",
            "MSAAUTH=", has_cookie(session, "__Host-MSAAUTH"),
            "AMCSecAuth=", has_cookie(session, "AMCSecAuth"),
            "JWT=", has_cookie(session, "AMCSecAuthJWT"),
            "WLSSC=", has_cookie(session, "WLSSC"),
        )

        urls = [
            "https://account.live.com/Activity",
            "https://account.live.com/Activity?mkt=en-US",
            "https://account.live.com/Activity.aspx",
            "https://account.microsoft.com/security",
            "https://account.microsoft.com/security#/activity",
            "https://account.microsoft.com/account-security/recent-activity",
            "https://account.live.com/proofs/manage/additional?mkt=en-US&refd=account.microsoft.com&refp=security",
        ]

        for url in urls:
            r = await session.get(url, follow_redirects=True)
            text = r.text or ""
            final = str(r.url)
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", url.split("//", 1)[-1])[:80]
            path = OUT_DIR / f"activity_{slug}.html"
            path.write_text(text)

            title_m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
            title = re.sub(r"\s+", " ", title_m.group(1)).strip()[:120] if title_m else ""
            events, text_events = _extract_activities(text)

            # Keyword sniffs for security-change style events
            interesting = []
            for pat, label in (
                (r"password (?:changed|reset|updated)", "password_change"),
                (r"security (?:info|email|phone|code)", "security_info"),
                (r"recovery code", "recovery_code"),
                (r"phone number", "phone"),
                (r"text message", "sms"),
                (r"authenticator|two-step|2-step", "2fa"),
                (r"passkey|windows hello|fido", "passkey"),
                (r"signed in|sign-in|signin", "signin"),
                (r"unusual", "unusual"),
                (r"app password", "app_password"),
                (r"alias|primary alias", "alias"),
            ):
                if re.search(pat, text, re.I):
                    # grab nearby context
                    for m in re.finditer(pat, text, re.I):
                        ctx = text[max(0, m.start() - 80) : m.end() + 120]
                        ctx = re.sub(r"<[^>]+>", " ", ctx)
                        ctx = re.sub(r"\s+", " ", ctx).strip()
                        interesting.append({"label": label, "ctx": ctx[:220]})
                        if len([i for i in interesting if i["label"] == label]) >= 3:
                            break

            # IP / location-ish
            ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
            # filter obvious non-IPs from versions
            ips = [ip for ip in ips if not ip.startswith("0.") and ip.count(".") == 3][:30]

            entry = {
                "url": url,
                "status": r.status_code,
                "final": final,
                "title": title,
                "len": len(text),
                "saved": str(path),
                "json_events": events[:50],
                "text_events": text_events[:30],
                "interesting": interesting[:40],
                "ips": ips,
                "is_login_wall": "login.live.com" in final or "login.microsoftonline.com" in final
                or "Enter your password" in text
                or title.lower() in ("sign in", "sign in to your microsoft account"),
            }
            report["pages"][url] = entry
            print(
                f"\n=== {url}\n status={r.status_code} final={final[:120]}\n"
                f" title={title!r} len={len(text)} login_wall={entry['is_login_wall']}\n"
                f" json_events={len(events)} text_events={len(text_events)} "
                f"interesting={len(interesting)} ips={ips[:5]}"
            )
            for e in events[:15]:
                print(" EVENT", json.dumps(e, default=str)[:400])
            for t in text_events[:10]:
                print(" TEXT ", t[:200])
            for i in interesting[:12]:
                print(" HINT ", i["label"], ":", i["ctx"][:180])

        out = OUT_DIR / "mcfa_activity_report.json"
        out.write_text(json.dumps(report, indent=2, default=str))
        print("\nWrote", out)

    finally:
        await close_session(session)


if __name__ == "__main__":
    asyncio.run(main())
