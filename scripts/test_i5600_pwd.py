#!/usr/bin/env python3
"""Deep i5600 + AddAssocId debug after password accept."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from securing.auth.initial_session import get_session
from securing.utils.cookies.get_livedata import livedata
from securing.utils.login_pwd import login_pwd
from securing.auth.handle_redirects import handle_redirects, get_data
from securing.auth.polish_host import polish_host
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.security_information import (
    _page_id,
    _extract_url_post_sft,
    _extract_email_otc_proof,
    _sso_fields,
    _find_t0,
)
from securing.utils.security.change_primary_alias import _extract_canary, _emails_from_manage

EMAIL = "amazing_fam.iyq28s64@outlook.com"
PASSWORD = "NZ6b0bbGHapxOFpv"


async def main():
    session = get_session()
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
            print("login fail")
            return
    await polish_host(session, msa)

    r = await session.get("https://account.live.com/names/manage", follow_redirects=True)
    html = r.text or ""
    print("manage url", r.url)
    print("pageId", _page_id(html), "canary", bool(_extract_canary(html)))
    proof = _extract_email_otc_proof(html)
    print("proof", proof)
    # dump arrUserProofs snippet
    m = re.search(r"arrUserProofs\s*[:=]\s*(\[.*?\])\s*[,;]", html, re.S)
    if m:
        print("arrUserProofs", m.group(1)[:800])
    else:
        # try JSON in ServerData
        m2 = re.search(r'"arrUserProofs":(\[.*?\])\s*[,}]', html, re.S)
        print("arrUserProofs json", (m2.group(1)[:800] if m2 else None))

    url_post, sft = _extract_url_post_sft(html)
    print("urlPost", (url_post or "")[:120], "sft", bool(sft))

    if url_post and sft:
        page2 = await login_pwd(session, EMAIL, url_post, PASSWORD, sft)
        print("after pwd pageId", _page_id(page2), "t0", bool(_find_t0(page2)))
        print("pprid", "pprid" in (page2 or "").lower())
        sso, miss = _sso_fields(page2 or "")
        print("sso", bool(sso), "missing", miss)
        Path("/tmp/i5600_after_pwd.html").write_text(page2 or "")
        print("wrote /tmp/i5600_after_pwd.html len", len(page2 or ""))

        # If SSO, post it
        if sso:
            resp = await session.post(
                sso["action"],
                data={"pprid": sso["pprid"], "NAP": sso["NAP"], "ANON": sso["ANON"], "t": sso["t"]},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=True,
            )
            print("after sso", resp.url, _page_id(resp.text), "canary", bool(_extract_canary(resp.text or "")))

        r2 = await session.get("https://account.live.com/names/manage", follow_redirects=True)
        print("manage2", r2.url, _page_id(r2.text), "canary", bool(_extract_canary(r2.text or "")), "emails", _emails_from_manage(r2.text or ""))
        Path("/tmp/manage2.html").write_text(r2.text or "")


if __name__ == "__main__":
    asyncio.run(main())
