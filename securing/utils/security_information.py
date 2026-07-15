import logging
import html
import re
from urllib.parse import urljoin, unquote

import httpx

from securing.utils.cookies.get_email_code import get_email_code

_PROOFS_URL = "https://account.live.com/proofs/Manage/additional"
_MAX_BRIDGE_HOPS = 10

# PageIDs where type=28 KMSI is valid. Never use KMSI on MFA (i5600) or login (i5030).
_KMSI_PAGE_IDS = frozenset({"i5245", "i5643"})


def _title(text: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.DOTALL)
    if not m:
        return "(no title)"
    return re.sub(r"\s+", " ", m.group(1)).strip()[:120]


def _page_id(text: str) -> str | None:
    m = re.search(r'PageID" content="([^"]+)"', text)
    return m.group(1) if m else None


def _find_t0(text: str) -> re.Match | None:
    return re.search(r"var\s+t0\s*=\s*(\{.*?\});", text, re.DOTALL)


def _is_ms_error_page(text: str, url: str = "") -> bool:
    u = (url or "").lower()
    if "error.aspx" in u or "errcode=" in u:
        return True
    # Language-save shells on error.aspx also embed a t0 — never treat as proofs t0.
    if "errcode=" in (text or "").lower() and "error.aspx" in (text or "").lower():
        return True
    return False


def _still_on_i5600(text: str) -> bool:
    pid = _page_id(text or "")
    if pid in ("i5600", "i5030"):
        return True
    lower = (text or "").lower()
    return "help us protect" in lower and "arruserproofs" in lower


def _has_auth_redirect_form(text: str) -> bool:
    lower = (text or "").lower()
    return (
        "account.live.com/auth/redirect" in lower
        and 'name="code"' in lower
        and 'name="state"' in lower
    )


def _page_debug(text: str, *, url: str = "", status: int | None = None) -> str:
    lower = text.lower()
    flags = []
    if _find_t0(text):
        flags.append("has_t0")
    if "object moved" in lower:
        flags.append("object_moved")
    if "fmhf" in lower:
        flags.append("fmHF")
    if 'name="pprid"' in lower or "name='pprid'" in lower:
        flags.append("pprid")
    if 'name="nap"' in lower:
        flags.append("NAP")
    if 'name="anon"' in lower:
        flags.append("ANON")
    if 'name="ipt"' in lower:
        flags.append("ipt")
    if "jsdisabled.srf" in lower:
        flags.append("jsDisabled_noscript")
    if "help us protect" in lower:
        flags.append("help_protect")
    if "urlpost" in lower:
        flags.append("urlPost")
    if '"sft"' in lower or "sfttag" in lower:
        flags.append("sFT")
    if "arruserproofs" in lower:
        flags.append("arrUserProofs")
    action = re.search(r'action="([^"]+)"', text, re.I)
    return (
        f"status={status} url={url!s} title={_title(text)!r} "
        f"pageId={_page_id(text)!r} "
        f"flags={flags} action={(action.group(1)[:180] if action else None)!r} "
        f"len={len(text)} snippet={text[:500]!r}"
    )


def _object_moved_href(text: str) -> str | None:
    if "object moved" not in text.lower():
        return None
    m = re.search(r'href="([^"]+)"', text, re.I)
    if not m:
        return None
    return html.unescape(m.group(1).replace("&amp;", "&"))


def _meta_refresh_url(text: str) -> str | None:
    """Return meta-refresh URL, ignoring noscript jsDisabled dead-ends."""
    for m in re.finditer(
        r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\']?\d+\s*;\s*URL=([^"\'>\s]+)',
        text,
        re.I,
    ):
        url = html.unescape(m.group(1).replace("&amp;", "&"))
        if "jsdisabled.srf" in url.lower():
            continue
        start = m.start()
        noscript_open = text.rfind("<noscript", 0, start)
        noscript_close = text.rfind("</noscript>", 0, start)
        if noscript_open > noscript_close:
            continue
        return url
    return None


def _extract_hidden_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for tag in re.findall(r"<input[^>]+>", text, re.I):
        name_m = re.search(r'name=["\']([^"\']+)["\']', tag, re.I)
        if not name_m:
            continue
        val_m = re.search(r'value=["\']([^"\']*)["\']', tag, re.I)
        fields[name_m.group(1)] = html.unescape(val_m.group(1)) if val_m else ""
    return fields


def _extract_form_action(text: str, base_url: str = "") -> str | None:
    m = re.search(r'<form[^>]*action=["\']([^"\']+)["\']', text, re.I)
    if not m:
        return None
    action = html.unescape(m.group(1).replace("&amp;", "&"))
    if action.startswith("http"):
        return action
    return urljoin(base_url or "https://login.live.com/", action)


def _sso_fields(text: str) -> tuple[dict[str, str] | None, list[str]]:
    action = _extract_form_action(text)
    fields = _extract_hidden_fields(text)
    needed = ("pprid", "NAP", "ANON", "t")
    missing = [k for k in needed if k not in fields or fields[k] == ""]
    if not action:
        missing.insert(0, "action")
    if missing:
        return None, missing
    return {
        "action": action,
        "pprid": fields["pprid"],
        "NAP": fields["NAP"],
        "ANON": fields["ANON"],
        "t": fields["t"],
    }, []


def _extract_url_post_sft(text: str) -> tuple[str | None, str | None]:
    url_post = None
    for pat in (
        r'"urlPost"\s*:\s*"(https://login\.live\.com/ppsecure/post\.srf[^"]+)"',
        r'"urlPost"\s*:\s*"(https://[^"]+post\.srf[^"]+)"',
        r'action="(https://login\.live\.com/ppsecure/post\.srf[^"]*)"',
    ):
        m = re.search(pat, text)
        if m:
            url_post = m.group(1)
            break

    sft = None
    m = re.search(r'"sFT"\s*:\s*"([^"]+)"', text)
    if m:
        sft = m.group(1)
    if not sft:
        m = re.search(r'"sFTTag"\s*:\s*"((?:\\.|[^"\\])*)"', text)
        if m:
            tag = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
            vm = re.search(r'value="([^"]+)"', tag)
            if vm:
                sft = vm.group(1)
    if not sft:
        m = re.search(r'name="PPFT"[^>]*value="([^"]+)"', text, re.I)
        if m:
            sft = m.group(1)
    return url_post, sft


def _wreply_from_url(url: str) -> str | None:
    m = re.search(r"[?&]wreply=([^&]+)", url, re.I)
    if not m:
        return None
    return unquote(m.group(1))


def _page_fingerprint(text: str, url: str) -> str:
    return f"{_page_id(text) or '?'}|{_title(text)}|{url.split('&ct=')[0][:180]}"


def _extract_email_otc_proof(text: str) -> dict[str, str] | None:
    """Pull the first email OTC proof from arrUserProofs on MFA pages (i5600)."""
    m = re.search(r'"arrUserProofs"\s*:\s*(\[.*?\])\s*,\s*"', text, re.DOTALL)
    if not m:
        # Fallback: looser match
        m = re.search(r'"arrUserProofs"\s*:\s*(\[.*?\])', text, re.DOTALL)
    if not m:
        return None
    blob = m.group(1)
    # Prefer email proofs (type 1) with otcEnabled
    for proof_m in re.finditer(
        r'\{[^{}]*?"type"\s*:\s*1[^{}]*?\}',
        blob,
        re.DOTALL,
    ):
        chunk = proof_m.group(0)
        if '"otcEnabled":true' not in chunk and '"otcEnabled": true' not in chunk:
            continue
        data_m = re.search(r'"data"\s*:\s*"((?:\\.|[^"\\])*)"', chunk)
        display_m = re.search(r'"display"\s*:\s*"((?:\\.|[^"\\])*)"', chunk)
        if not data_m:
            continue
        return {
            "data": data_m.group(1),
            "display": display_m.group(1) if display_m else "",
        }
    # Any otcEnabled proof
    data_m = re.search(
        r'"otcEnabled"\s*:\s*true[^{}]*?"data"\s*:\s*"((?:\\.|[^"\\])*)"'
        r'|"data"\s*:\s*"((?:\\.|[^"\\])*)"[^{}]*?"otcEnabled"\s*:\s*true',
        blob,
        re.DOTALL,
    )
    if data_m:
        return {"data": data_m.group(1) or data_m.group(2), "display": ""}
    return None


def _clean_password(password: str | None) -> str | None:
    if not password:
        return None
    # Strip UNVERIFIED annotations from recovery_secure
    cleaned = re.sub(r"\s*\(UNVERIFIED[^)]*\)\s*$", "", password).strip()
    if not cleaned or cleaned == "Couldn't Change!":
        return None
    return cleaned


async def _get(session: httpx.AsyncClient, url: str) -> httpx.Response:
    return await session.get(url, follow_redirects=True)


async def _post_form(
    session: httpx.AsyncClient,
    action: str,
    data: dict[str, str],
) -> httpx.Response:
    return await session.post(
        url=action,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=data,
        follow_redirects=True,
    )


def _gotc_state_ok(data: dict) -> bool:
    """True only when GetOneTimeCode reports a real send.

    MS returns application ``State`` in the JSON body (not HTTP status).
    Observed: ``{"State":204}`` = reject / wrong purpose / not sent.
    Success is typically State 200 or 201 (sometimes with SessionId).
    """
    err = data.get("error") or data.get("ErrorCode") or data.get("errorCode")
    if err not in (None, "", 0, "0"):
        return False
    state = data.get("State")
    if state is None:
        state = data.get("state")
    if state is not None:
        try:
            state_i = int(state)
        except (TypeError, ValueError):
            return False
        # 200/201 = sent; 204/205/etc = not sent
        return state_i in (200, 201)
    # No State field — require a positive success marker
    if data.get("SessionId") or data.get("sessionId"):
        return True
    return False


async def _send_i5600_otc(
    session: httpx.AsyncClient,
    *,
    login: str,
    sft: str,
    sent_proof: str,
    security_email: str,
) -> bool:
    """Request MFA email OTC via GetOneTimeCode.

    Prefer eOTT_OtcLogin (same as login OTP). PrivProofConfirm often returns
    State 204 on proofs MFA and must NOT be treated as success.
    """
    purposes = (
        "eOTT_OtcLogin",
        "eOTT_PrivProofConfirm",
        "eOTT_ConfirmEmail",
        "eOTT_AddProof",
    )
    for purpose in purposes:
        payload = {
            "login": login,
            "flowtoken": sft,
            "purpose": purpose,
            "channel": "Email",
            "ChallengeViewSupported": "1",
            "AltEmailE": sent_proof,
            "lcid": "1033",
            "ProofConfirmation": security_email,
        }
        try:
            resp = await session.post(
                url="https://login.live.com/GetOneTimeCode.srf?id=38936",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data=payload,
            )
        except Exception:
            logging.exception("security_information: GetOneTimeCode %s failed", purpose)
            continue

        body = resp.text or ""
        logging.info(
            "security_information: GetOneTimeCode purpose=%s status=%s body=%r",
            purpose,
            resp.status_code,
            body[:400],
        )
        if resp.status_code != 200 or not body.strip():
            continue
        try:
            data = resp.json()
        except Exception:
            # Non-JSON 200 — treat as sent if not an obvious HTML error page
            if "sErrTxt" not in body and "<html" not in body.lower():
                return True
            continue
        if not isinstance(data, dict):
            continue
        if _gotc_state_ok(data):
            logging.info(
                "security_information: GetOneTimeCode purpose=%s accepted (State=%s)",
                purpose,
                data.get("State", data.get("state")),
            )
            return True
        logging.warning(
            "security_information: GetOneTimeCode purpose=%s rejected (State=%s error=%s)",
            purpose,
            data.get("State", data.get("state")),
            data.get("error") or data.get("ErrorCode") or data.get("errorCode"),
        )
    return False


async def _send_i5600_type18(
    session: httpx.AsyncClient,
    *,
    url_post: str,
    sft: str,
    login: str,
    sent_proof: str,
    security_email: str,
    proof_confirmation_required: bool = False,
    page_html: str | None = None,
) -> tuple[str, str, str, httpx.Response]:
    """Browser-native 'Send code' post.

    Returns ``(url_post, sft, sent_proof, response)``.

    When ``fProofConfirmationRequired`` is true, include ProofConfirmation on
    type=18. If that hits errcode=1086, retry once with the opposite PC setting.
    """
    if page_html and re.search(
        r'"fProofConfirmationRequired"\s*:\s*true', page_html or "", re.I
    ):
        proof_confirmation_required = True

    async def _post(pc: str) -> httpx.Response:
        return await session.post(
            url=url_post,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "login": login,
                "loginfmt": login,
                "SentProofIDE": sent_proof,
                "PPFT": sft,
                "type": "18",
                "GeneralVerify": "false",
                "canary": "",
                "sacxt": "1",
                "hpgrequestid": "",
                "hideSmsInMfaProofs": "false",
                "AddTD": "true",
                "ProofConfirmation": pc,
            },
            follow_redirects=True,
        )

    # Prefer empty PC first. Filled PC often hits errcode=1086 on SA_20MIN
    # i5600 (rylan-class). Retry with security email when still challenged.
    pc = ""
    send_resp = await _post(pc)
    send_text = send_resp.text or ""
    logging.info(
        "security_information: type=18 (pc=%s) → %s",
        "set" if pc else "empty",
        _page_debug(send_text, url=str(send_resp.url), status=send_resp.status_code),
    )

    hit_1086 = (
        "errcode=1086" in str(send_resp.url).lower()
        or "errcode=1086" in send_text.lower()
    )
    still_i5600 = _still_on_i5600(send_text)
    if security_email and (hit_1086 or (still_i5600 and proof_confirmation_required)):
        logging.info(
            "security_information: type=18 retry with ProofConfirmation "
            "(1086=%s still_i5600=%s required=%s)",
            hit_1086,
            still_i5600,
            proof_confirmation_required,
        )
        send_resp = await _post(security_email.strip())
        send_text = send_resp.text or ""
        logging.info(
            "security_information: type=18 retry → %s",
            _page_debug(send_text, url=str(send_resp.url), status=send_resp.status_code),
        )
        if "errcode=1086" in str(send_resp.url).lower() or "errcode=1086" in send_text.lower():
            logging.warning("security_information: type=18 with-PC also hit 1086")

    url_post2, sft2 = _extract_url_post_sft(send_text)
    if url_post2:
        url_post = url_post2
    if sft2:
        sft = sft2
    proof2 = _extract_email_otc_proof(send_text)
    if proof2:
        sent_proof = proof2["data"]
    return url_post, sft, sent_proof, send_resp


async def _finish_i5600_leave(
    session: httpx.AsyncClient,
    resp: httpx.Response | None,
    *,
    label: str,
) -> httpx.Response | None:
    """If type=18/password already left MFA, finish continue forms and return it."""
    if resp is None:
        return None
    text = resp.text or ""
    url = str(getattr(resp, "url", "") or "")

    if _is_ms_error_page(text, url):
        return None

    # OAuth continue form — same hop that unblocks AddAssocId / names/manage
    if _has_auth_redirect_form(text):
        try:
            from securing.utils.security.change_primary_alias import (
                _submit_auth_redirect,
            )

            redirected = await _submit_auth_redirect(session, text)
            if redirected is not None:
                print(f"[+] - {label} cleared via auth/redirect (no OTP needed)")
                logging.info(
                    "security_information: %s left i5600 via auth/redirect", label
                )

                class _R:
                    def __init__(self, body: str):
                        self.text = body
                        self.url = "https://account.live.com/auth/redirect"
                        self.status_code = 200

                return _R(redirected)
        except Exception:
            logging.exception("security_information: auth/redirect finish failed")

    if _still_on_i5600(text):
        return None

    # Left MFA (KMSI / SSO / proofs / manage)
    if _find_t0(text) or _page_id(text) not in ("i5600", "i5030"):
        print(f"[+] - {label} cleared without email OTP")
        logging.info(
            "security_information: %s left i5600 (pageId=%s)",
            label,
            _page_id(text),
        )
        return resp
    return None


async def _complete_i5600_email_otc(
    session: httpx.AsyncClient,
    text: str,
    *,
    security_email: str,
    account_email: str | None,
    password: str | None = None,
    wait_slices: tuple[float, ...] = (45.0, 60.0, 45.0),
    label: str = "Proofs MFA",
    try_password_first: bool = False,
) -> httpx.Response | None:
    """Finish 'Help us protect your account' (i5600) via security-email OTC.

    Order: optional password → type=18 (may clear MFA without OTP) →
    GetOneTimeCode → short/long mail wait → password last resort.

    Fail-fast when type=18 stays on i5600 AND every GetOneTimeCode purpose
    rejects (203/204) — waiting minutes never helps; MS did not queue mail.
    """
    import time as _time

    url_post, sft = _extract_url_post_sft(text)
    proof = _extract_email_otc_proof(text)
    if not url_post or not sft or not proof:
        logging.warning(
            "security_information: i5600 missing urlPost/sFT/proof "
            "(urlPost=%s sFT=%s proof=%s)",
            bool(url_post),
            bool(sft),
            bool(proof),
        )
        return None

    login = (account_email or "").strip()
    sent_proof = proof["data"]
    password = _clean_password(password)
    logging.info(
        "security_information: i5600 email OTC challenge display=%s — sending code",
        proof.get("display") or "(unknown)",
    )

    def _wrap(page: str, url: str = ""):
        class _R:
            def __init__(self, body: str):
                self.text = body
                self.url = url or url_post
                self.status_code = 200

        return _R(page)

    async def _password_attempt() -> httpx.Response | None:
        if not (password and login and "@" in login):
            return None
        print(f"[~] - {label} — trying password on i5600…")
        try:
            from securing.utils.login_pwd import login_pwd

            page = await login_pwd(session, login, url_post, password, sft)
            if not page:
                return None
            finished = await _finish_i5600_leave(
                session,
                _wrap(page),
                label=label,
            )
            if finished is not None:
                print(f"[+] - {label} accepted password")
                return finished
            logging.warning(
                "security_information: password did not leave MFA (pageId=%s)",
                _page_id(page),
            )
        except Exception:
            logging.exception("security_information: i5600 password fallback failed")
        return None

    if try_password_first:
        early = await _password_attempt()
        if early is not None:
            return early

    print(f"[~] - {label} (Help us protect) — sending security-email OTP…")
    send_started = _time.time()

    logging.info("security_information: i5600 trying type=18 first")
    url_post, sft, sent_proof, type18_resp = await _send_i5600_type18(
        session,
        url_post=url_post,
        sft=sft,
        login=login,
        sent_proof=sent_proof,
        security_email=security_email,
        page_html=text,
    )
    finished = await _finish_i5600_leave(session, type18_resp, label=label)
    if finished is not None:
        return finished

    type18_text = type18_resp.text or ""
    if _still_on_i5600(type18_text):
        text = type18_text
        url_post2, sft2 = _extract_url_post_sft(type18_text)
        if url_post2:
            url_post = url_post2
        if sft2:
            sft = sft2
        proof2 = _extract_email_otc_proof(type18_text)
        if proof2:
            sent_proof = proof2["data"]

    gotc_ok = await _send_i5600_otc(
        session,
        login=login,
        sft=sft,
        sent_proof=sent_proof,
        security_email=security_email,
    )
    if gotc_ok:
        logging.info("security_information: GetOneTimeCode confirmed send after type=18")

    still_challenged = _still_on_i5600(type18_text) or _still_on_i5600(text)
    if still_challenged and not gotc_ok:
        slices = (18.0,)
        print(
            f"[!] - {label}: MS did not confirm OTP send "
            "(GetOneTimeCode rejected) — short wait only"
        )
        logging.warning(
            "security_information: %s fail-fast wait — GOTC rejected and still on i5600",
            label,
        )
    else:
        slices = wait_slices or (45.0, 60.0, 45.0)

    code = None
    for i, slice_t in enumerate(slices):
        code = await get_email_code(security_email, timeout=slice_t, since=send_started)
        if code:
            break
        if i == 0 and len(slices) > 1:
            logging.warning(
                "security_information: no OTP after %.0fs — resending type=18",
                slice_t,
            )
            print(f"[~] - No {label} OTP yet — resending security-email code…")
            send_started = _time.time()
            url_post, sft, sent_proof, type18_resp = await _send_i5600_type18(
                session,
                url_post=url_post,
                sft=sft,
                login=login,
                sent_proof=sent_proof,
                security_email=security_email,
                page_html=text,
            )
            finished = await _finish_i5600_leave(session, type18_resp, label=label)
            if finished is not None:
                return finished
            await _send_i5600_otc(
                session,
                login=login,
                sft=sft,
                sent_proof=sent_proof,
                security_email=security_email,
            )

    if not code:
        late = await _password_attempt()
        if late is not None:
            return late

        logging.error(
            "security_information: no OTP arrived for %s during i5600 challenge",
            security_email,
        )
        print(f"[X] - No security-email OTP for {label}")
        return None

    print(f"[+] - Got {label} OTP ({code})")
    logging.info("security_information: submitting i5600 OTC")

    last = None
    for otc_type in ("19", "27"):
        payload = {
            "login": login,
            "loginfmt": login,
            "otc": code,
            "SentProofIDE": sent_proof,
            "PPFT": sft,
            "type": otc_type,
            "GeneralVerify": "false",
            "AddTD": "true",
            "canary": "",
            "sacxt": "1",
            "hpgrequestid": "",
            "hideSmsInMfaProofs": "false",
            "infoPageShown": "1",
            "ProofConfirmation": security_email,
        }
        last = await session.post(
            url=url_post,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=payload,
            follow_redirects=True,
        )
        logging.info(
            "security_information: i5600 OTC type=%s → %s",
            otc_type,
            _page_debug(last.text, url=str(last.url), status=last.status_code),
        )
        finished = await _finish_i5600_leave(session, last, label=label)
        if finished is not None:
            return finished
        if _find_t0(last.text) and not _is_ms_error_page(last.text, str(last.url)):
            return last
        pid = _page_id(last.text)
        if pid not in ("i5600", "i5030") and not _still_on_i5600(last.text or ""):
            return last
        if '"sErrTxt"' in last.text and re.search(
            r'"sErrTxt"\s*:\s*"[^"]+', last.text
        ):
            err = re.search(r'"sErrTxt"\s*:\s*"((?:\\.|[^"])*)"', last.text)
            if err and err.group(1).strip():
                logging.warning(
                    "security_information: i5600 OTC type=%s error=%s",
                    otc_type,
                    err.group(1)[:160],
                )
                _, sft3 = _extract_url_post_sft(last.text)
                if sft3:
                    sft = sft3
                continue
        if not _still_on_i5600(last.text or ""):
            return last
    return last


async def _try_password_on_login_page(
    session: httpx.AsyncClient,
    text: str,
    *,
    account_email: str,
    password: str,
) -> httpx.Response | None:
    """If proofs SSO bounced to i5030 login, try password once."""
    from securing.utils.login_pwd import login_pwd

    url_post, sft = _extract_url_post_sft(text)
    if not url_post or not sft:
        return None
    logging.info("security_information: i5030 — attempting password re-auth")
    print("[~] - Proofs bounced to login — retrying with password…")
    try:
        page = await login_pwd(session, account_email, url_post, password, sft)
    except Exception:
        logging.exception("security_information: password re-auth failed")
        return None
    # May land on KMSI / SSO / proofs
    url_post2, sft2 = _extract_url_post_sft(page)
    pid = _page_id(page)
    if pid in _KMSI_PAGE_IDS and url_post2 and sft2:
        resp = await session.post(
            url=url_post2,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=f"PPFT={sft2}&canary=&LoginOptions=3&type=28&hpgrequestid=&ctx=",
            follow_redirects=True,
        )
        return resp
    # Wrap as a fake response-like object via a simple namespace
    class _R:
        def __init__(self, body: str):
            self.text = body
            self.url = "https://login.live.com/login.srf"
            self.status_code = 200

    return _R(page)


async def _bridge_to_proofs(
    session: httpx.AsyncClient,
    text: str,
    url: str,
    status: int | None,
    *,
    security_email: str | None = None,
    account_email: str | None = None,
    password: str | None = None,
    skip_i5600_otp: bool = False,
) -> tuple[str, str, int | None]:
    """Follow Object-moved / forms / SSO / KMSI / MFA-OTC until t0 or give up.

    Never follows noscript jsDisabled.srf — that is a JS-required dead end.
    Never loops type=28 KMSI on MFA (i5600) or login (i5030) pages.

    If ``skip_i5600_otp`` is True (recovery already succeeded), bail out of
    "Help us protect" without waiting minutes for a security-email OTP.
    """
    current = text
    current_url = url
    current_status = status
    seen: dict[str, int] = {}
    kmsi_attempts = 0
    otc_attempted = False
    password_attempted = False
    password = _clean_password(password)

    for hop in range(_MAX_BRIDGE_HOPS):
        if _find_t0(current) and not _is_ms_error_page(current, current_url):
            logging.info(
                "security_information: found t0 after %s bridge hop(s) (%s)",
                hop,
                _page_debug(current, url=current_url, status=current_status),
            )
            return current, current_url, current_status

        fp = _page_fingerprint(current, current_url)
        seen[fp] = seen.get(fp, 0) + 1
        if seen[fp] >= 3:
            logging.warning(
                "security_information: same page repeated %s times — stopping bridge (%s)",
                seen[fp],
                _page_debug(current, url=current_url, status=current_status),
            )
            break

        if "jsdisabled.srf" in current_url.lower():
            wreply = _wreply_from_url(current_url)
            target = wreply or _PROOFS_URL
            logging.warning(
                "security_information: landed on jsDisabled — recovering via %s",
                target[:240],
            )
            resp = await _get(session, target)
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            continue

        logging.info(
            "security_information: bridge hop %s/%s — %s",
            hop + 1,
            _MAX_BRIDGE_HOPS,
            _page_debug(current, url=current_url, status=current_status),
        )

        moved = _object_moved_href(current)
        if moved and "jsdisabled.srf" not in moved.lower():
            logging.info("security_information: following Object moved → %s", moved[:240])
            resp = await _get(session, moved)
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            continue

        sso, missing = _sso_fields(current)
        if sso:
            logging.info(
                "security_information: posting SSO continue form action=%s",
                sso["action"][:240],
            )
            resp = await _post_form(
                session,
                sso["action"],
                {
                    "pprid": sso["pprid"],
                    "NAP": sso["NAP"],
                    "ANON": sso["ANON"],
                    "t": sso["t"],
                },
            )
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            continue

        fields = _extract_hidden_fields(current)
        action = _extract_form_action(current, current_url)
        if action and "pprid" in fields and ("ipt" in fields or "NAP" in fields or "t" in fields):
            logging.info(
                "security_information: auto-submitting continue form action=%s fields=%s",
                action[:240],
                sorted(fields.keys()),
            )
            resp = await _post_form(session, action, fields)
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            continue

        if action and ("fmHF" in current or fields) and fields and "pprid" in fields:
            logging.info(
                "security_information: auto-submitting form action=%s fields=%s",
                action[:240],
                sorted(fields.keys()),
            )
            resp = await _post_form(session, action, fields)
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            continue

        pid = _page_id(current)

        # i5600 = "Help us protect" MFA — needs email OTC, NOT type=28 KMSI
        if pid == "i5600" or (
            "help us protect" in current.lower() and "arrUserProofs" in current
        ):
            if skip_i5600_otp:
                logging.warning(
                    "security_information: i5600 skipped (recovery already held) — %s",
                    _page_debug(current, url=current_url, status=current_status),
                )
                print(
                    "[!] - Proofs MFA (Help us protect) — skipping security-email OTP "
                    "(recovery already secured)"
                )
                break
            if otc_attempted:
                logging.warning(
                    "security_information: i5600 OTC already attempted — stopping"
                )
                break
            if not security_email or security_email == "Couldn't Change!":
                logging.warning(
                    "security_information: i5600 MFA but no security_email available"
                )
                break
            otc_attempted = True
            resp = await _complete_i5600_email_otc(
                session,
                current,
                security_email=security_email,
                account_email=account_email,
                password=password,
                try_password_first=bool(password),
                wait_slices=(25.0, 35.0) if password else (30.0, 45.0, 45.0),
            )
            if resp is None:
                break
            current, current_url, current_status = (
                resp.text,
                str(getattr(resp, "url", current_url)),
                getattr(resp, "status_code", current_status),
            )
            # After OTC, pull wreply/proofs if still not on t0
            if not _find_t0(current):
                wreply = _wreply_from_url(url) or _wreply_from_url(current_url)
                resp2 = await _get(session, wreply or _PROOFS_URL)
                current, current_url, current_status = (
                    resp2.text,
                    str(resp2.url),
                    resp2.status_code,
                )
            continue

        # i5030 / generic login — password once, never KMSI-loop
        if pid in ("i5030", "i5026") or (
            "sign in to your microsoft account" in current.lower()
            and "arrUserProofs" not in current
            and pid not in _KMSI_PAGE_IDS
        ):
            if (
                not password_attempted
                and password
                and account_email
                and "@" in account_email
            ):
                password_attempted = True
                resp = await _try_password_on_login_page(
                    session,
                    current,
                    account_email=account_email,
                    password=password,
                )
                if resp is not None:
                    current = resp.text
                    current_url = str(getattr(resp, "url", current_url))
                    current_status = getattr(resp, "status_code", current_status)
                    if not _find_t0(current):
                        wreply = _wreply_from_url(url) or _wreply_from_url(current_url)
                        resp2 = await _get(session, wreply or _PROOFS_URL)
                        current, current_url, current_status = (
                            resp2.text,
                            str(resp2.url),
                            resp2.status_code,
                        )
                    continue
            logging.warning(
                "security_information: stuck on login page %s — session too weak for proofs",
                pid,
            )
            break

        # Real KMSI page only (i5245 etc.)
        url_post, sft = _extract_url_post_sft(current)
        if url_post and sft and pid in _KMSI_PAGE_IDS and kmsi_attempts < 2:
            kmsi_attempts += 1
            logging.info(
                "security_information: KMSI finish via urlPost (pageId=%s attempt=%s)",
                pid,
                kmsi_attempts,
            )
            resp = await session.post(
                url=url_post,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=f"PPFT={sft}&canary=&LoginOptions=3&type=28&hpgrequestid=&ctx=",
                follow_redirects=True,
            )
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            if not _find_t0(current):
                wreply = _wreply_from_url(url) or _wreply_from_url(current_url)
                resp2 = await _get(session, wreply or _PROOFS_URL)
                current, current_url, current_status = (
                    resp2.text,
                    str(resp2.url),
                    resp2.status_code,
                )
            continue

        if url_post and sft and pid not in _KMSI_PAGE_IDS:
            logging.info(
                "security_information: skipping type=28 on non-KMSI pageId=%s",
                pid,
            )

        refresh = _meta_refresh_url(current)
        if refresh:
            logging.info("security_information: following meta refresh → %s", refresh[:240])
            resp = await _get(session, refresh)
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            continue

        logging.warning(
            "security_information: bridge stuck — no t0/redirect/form "
            "(missing_sso=%s) %s",
            missing,
            _page_debug(current, url=current_url, status=current_status),
        )
        break

    return current, current_url, current_status


async def security_information(
    session: httpx.AsyncClient,
    *,
    security_email: str | None = None,
    account_email: str | None = None,
    password: str | None = None,
    skip_i5600_otp: bool = False,
):
    sec_info = await session.get(url=_PROOFS_URL, follow_redirects=True)
    logging.info(
        "security_information: initial proofs GET — %s",
        _page_debug(sec_info.text, url=str(sec_info.url), status=sec_info.status_code),
    )

    text = sec_info.text
    url = str(sec_info.url)
    status = sec_info.status_code
    bridge_kwargs = dict(
        security_email=security_email,
        account_email=account_email,
        password=password,
        skip_i5600_otp=skip_i5600_otp,
    )

    match = _find_t0(text)
    if not match:
        text, url, status = await _bridge_to_proofs(
            session, text, url, status, **bridge_kwargs
        )
        match = _find_t0(text)

    if not match:
        logging.info("security_information: retrying proofs/Manage/additional after bridge")
        retry = await session.get(url=_PROOFS_URL, follow_redirects=True)
        logging.info(
            "security_information: retry GET — %s",
            _page_debug(retry.text, url=str(retry.url), status=retry.status_code),
        )
        text, url, status = retry.text, str(retry.url), retry.status_code
        if not _find_t0(text):
            text, url, status = await _bridge_to_proofs(
                session, text, url, status, **bridge_kwargs
            )
        match = _find_t0(text)

    if not match:
        _, missing = _sso_fields(text)
        raise RuntimeError(
            "security_information: could not find var t0= on proofs page after SSO bridge. "
            f"missing_sso_fields={missing} "
            f"{_page_debug(text, url=url, status=status)}"
        )

    return match.group(1)
