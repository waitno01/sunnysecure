from securing.utils.cookies.get_email_code import get_email_code
from securing.utils.cookies.get_livedata import livedata
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
    Uses a fresh login page PPFT (not GetCredentialType FlowToken) to avoid
    false "incorrect password" pages from malformed login posts.
    """
    try:
        # Password can take a moment to propagate after RecoverUser
        await asyncio.sleep(2.0)

        live = await livedata(session)
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
        text = check.text or ""
        lower = text.lower()

        # Explicit wrong-password markers only
        hard_bad = (
            "that password is incorrect" in lower
            or "your account or password is incorrect" in lower
            or '"serrorcode":"80041012"' in lower
            or "serrorcode\\\":\\\"80041012" in lower
        )
        if hard_bad:
            logging.error(
                "Password verify BAD for %s (status=%s snippet=%s)",
                email,
                check.status_code,
                text[:300].replace("\n", " "),
            )
            return "bad"

        if (
            check.status_code in (302, 303)
            or "__Host-MSAAUTH" in session.cookies
            or "urlPost" in text
            or "account.live.com" in (check.headers.get("location") or "")
        ):
            logging.info("Password verify OK for %s (status=%s)", email, check.status_code)
            return "ok"

        logging.warning(
            "Password verify UNKNOWN for %s (status=%s snippet=%s)",
            email,
            check.status_code,
            text[:300].replace("\n", " "),
        )
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

    if "error" in data:
        err = data.get("error") or {}
        logging.error("%s: Microsoft error %s", step, err.get("code", data))
        return None

    return data


async def recover(session: httpx.AsyncClient, email: str, recovery_code: str, new_email: str, new_password: str):
    # Automates the recovery process through recovery code 
    
    data = await session.get(url=f"https://account.live.com/ResetPassword.aspx?wreply=https://login.live.com/oauth20_authorize.srf&mn={email}")
    logging.info(f"sRecovery: {data.text}")

    serverData = re.search(r"var\s+ServerData=(.*?)(?=;|$)", data.text)
    if not serverData:
        logging.error("recover: could not parse ServerData for %s", email)
        return "invalid"
    
    serverData = json.loads(serverData.group(1))
    decoded_token = codecs.decode(unquote(serverData["sRecoveryToken"]), "unicode_escape")

    recToken = await session.post(
        url = "https://account.live.com/API/Recovery/VerifyRecoveryCode",
        headers = {
            **MS_HEADERS,
            "canary": serverData["apiCanary"],
        },
        json = {
            "recoveryCode": recovery_code,
            "code": recovery_code,
            "scid": 100103,
            "token": decoded_token,
            "uiflvr": 1001
        }
    )

    recJson = _parse_json(recToken, "VerifyRecoveryCode")
    if not recJson or "apiCanary" not in recJson:
        return None

    canary = recJson["apiCanary"]
    token = recJson["token"]
    sendCode = await session.post(
        url = "https://account.live.com/api/Proofs/SendOtt", 
        headers = {
            **MS_HEADERS,
            "canary": canary,
        },
        json = {
            "associationType": "None",
            "action": "VerifyNewProof",
            "channel": "Email",
            "cxt": "MP",
            "proofId": new_email,
            "scid": 100103,
            "token": token,
            "uiflvr": 1001
        }
    )
    
    responseJson = _parse_json(sendCode, "SendOtt")
    if not responseJson or "apiCanary" not in responseJson:
        return None

    canary = responseJson["apiCanary"]
    code = await get_email_code(new_email)
    if not code:
        logging.error("recover: timed out waiting for OTP at %s", new_email)
        return None

    verifyCodeResponse = await session.post(
        url = "https://account.live.com/API/Proofs/VerifyCode",
        headers = {
            **MS_HEADERS,
            "canary": canary,
        },
        json = {
            "action": "VerifyOtc",
            "proofId": new_email,
            "scid": 100103,
            "token": token,
            "uiflvr": 1001,
            "code": code
        }
    )
    verifyCodeResponseJson = _parse_json(verifyCodeResponse, "VerifyCode")
    if not verifyCodeResponseJson or "apiCanary" not in verifyCodeResponseJson:
        return None

    canary = verifyCodeResponseJson["apiCanary"]

    # publicKey is required by RecoverUser for the password to actually stick.
    # Without it, MS often still returns recoveryCode + applies contactEmail,
    # but leaves the old password unchanged. Value from working MSA recovery clients.
    public_key = (
        verifyCodeResponseJson.get("publicKey")
        or recJson.get("publicKey")
        or "25CE4D96CB3A09A69CD847C69FC6D40AF4A4DE12"
    )

    recover_payload = {
        "contactEmail": new_email,
        "contactEpid": "",
        "password": new_password,
        "passwordExpiryEnabled": 0,
        "publicKey": public_key,
        "token": token,
    }

    finishJson = None
    for attempt in range(1, 4):
        finishSecure = await session.post(
            url="https://account.live.com/API/Recovery/RecoverUser",
            headers={
                **MS_HEADERS,
                "canary": canary,
            },
            json=recover_payload,
        )
        logging.info(
            "RecoverUser attempt %s status=%s body=%s",
            attempt,
            finishSecure.status_code,
            finishSecure.text[:800],
        )

        # Don't use _parse_json here — it drops responses that include an error
        # key even when recoveryCode is present.
        try:
            finishJson = finishSecure.json() if finishSecure.text.strip() else None
        except json.JSONDecodeError:
            finishJson = None

        if not finishJson:
            if attempt < 3:
                await asyncio.sleep(attempt * 2)
                continue
            return None

        err = finishJson.get("error") or {}
        err_code = str(err.get("code", ""))
        if err_code == "6001":
            logging.error("RecoverUser rate-limited (6001) for %s", email)
            return None
        if err_code:
            err_msg = str(err.get("data", err.get("message", ""))).lower()
            if any(k in err_msg or k in err_code.lower() for k in ("password", "passwd", "complexity", "banned")):
                logging.error("RecoverUser rejected password: %s", err)
                return None
            logging.error("RecoverUser error: %s", err)
            if attempt < 3:
                await asyncio.sleep(attempt * 2)
                continue
            return None

        if finishJson.get("recoveryCode"):
            print(f"[+] - RecoverUser OK (password length={len(new_password)})")
            return finishJson["recoveryCode"]

        if attempt < 3:
            await asyncio.sleep(attempt * 2)

    logging.error("RecoverUser missing recoveryCode after retries: %s", finishJson)
    return None
