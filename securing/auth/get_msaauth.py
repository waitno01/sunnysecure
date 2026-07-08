from securing.auth.handle_redirects import handle_redirects, get_data
from securing.auth.account_status import get_account_lock_reason
from urllib.parse import quote
import logging
import httpx
import re

async def get_msaauth(session: httpx.AsyncClient, email: str, flowtoken: str, odata: dict, code: str, ppft: str = None) -> dict | str | None:
    # First post request that gets __Host-MSAAUTH
    
    if not code:
        
        loginData = await session.post(
            url = odata["urlPost"],
            headers = {
                "host": "login.live.com",
                "Accept-Language": "en-US,en;q=0.5",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://login.live.com",
                "Referer": "https://login.live.com/",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Priority": "u=0, i"
            },
            data = {
                "login": email,
                "loginfmt": email,
                "slk": flowtoken,
                "psRNGCSLK": flowtoken,
                "type": "21",
                "PPFT": odata["ppft"]
            },
            follow_redirects = True
        )

        urlPost = re.search(r'"urlPost"\s*:\s*"([^\"]+)"', loginData.text)

    else:
        
        payload = {
            "login": email,
            "loginfmt": email,
            "SentProofIDE": flowtoken,
            "PPFT": odata["ppft"]
        }

        for i in range(2):
            
            # 1 - Normal Email OTP (Type 24)
            # 2 - Primary Email working as Security Email too (Type 27)
            # 3 - Phone Number
            match i:
                case 0:
                    payload["otc"] = code
                    payload["type"] = "27"
                case 1:
                    payload.pop("otc")
                    payload["npotc"] = code
                    payload["type"] = "24"
 
            loginData = await session.post(
                url = odata["urlPost"],
                headers = {
                    "host": "login.live.com",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://login.live.com",
                    "Referer": "https://login.live.com/",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "same-origin",
                    "Priority": "u=0, i"
                },
                data = payload,
                follow_redirects = True
            )

            print(f"Login attempt {i}")
            logging.info(f"Login attempt {i+1} response: {loginData.text}")
            urlPost = re.search(r'"urlPost"\s*:\s*"([^\"]+)"', loginData.text)
            print(dict(session.cookies))
            if '__Host-MSAAUTH' in session.cookies:
                break

    if '__Host-MSAAUTH' in session.cookies:
        logging.info(f"MSAAUTH cookie for {email}: {dict(session.cookies)['__Host-MSAAUTH']}")

        if not urlPost:
            data = await handle_redirects(session, loginData.text)
            if data == "Family":
                return "Family"
            if isinstance(data, dict) and data.get("urlPost"):
                return data
            parsed = get_data(loginData.text)
            if parsed:
                return parsed
            lock_reason = await get_account_lock_reason(email, loginData.text)
            if lock_reason:
                return {"_error": lock_reason}
            return {"_error": "MSAAUTH obtained but post-login redirect could not be parsed (unknown login page)."}

        sft_match = re.search(r'"sFT"\s*:\s*"([^"]+)"', loginData.text)
        if not sft_match:
            data = await handle_redirects(session, loginData.text)
            if isinstance(data, dict):
                return data
            lock_reason = await get_account_lock_reason(email, loginData.text)
            if lock_reason:
                return {"_error": lock_reason}
            return {"_error": "MSAAUTH obtained but login page did not include sFT token."}

        ppft = quote(sft_match.group(1), safe='-*')

        return {
            "urlPost" : urlPost.group(1),
            "ppft": ppft
        }

    lock_reason = await get_account_lock_reason(email, loginData.text)
    if lock_reason:
        return {"_error": lock_reason}
    return {"_error": "Login failed — no MSAAUTH cookie (wrong/expired OTP or Microsoft rejected login)."}
