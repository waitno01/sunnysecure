from securing.auth.handle_redirects import handle_redirects, get_data
from securing.auth.account_status import get_account_lock_reason
from securing.utils.cookies.safe_cookies import (
    cookies_as_dict,
    dedupe_cookies,
    get_cookie,
    has_cookie,
)
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
            dedupe_cookies(session)
            print(cookies_as_dict(session))
            if has_cookie(session, "__Host-MSAAUTH"):
                break

    dedupe_cookies(session)
    if has_cookie(session, "__Host-MSAAUTH"):
        logging.info(f"MSAAUTH cookie for {email}: {get_cookie(session, '__Host-MSAAUTH')}")

        if not urlPost:
            data = await handle_redirects(session, loginData.text)
            if data == "Family":
                return "Family"
            if isinstance(data, dict) and data.get("urlPost"):
                return data
            parsed = get_data(loginData.text)
            if parsed:
                return parsed
            if isinstance(data, str):
                parsed = get_data(data)
                if parsed:
                    return parsed
                # Privacy/identity continue may leave a page with ServerData tokens
                sft_m = re.search(r'"sFT"\s*:\s*"([^"]+)"', data)
                post_m = re.search(r'"urlPost"\s*:\s*"([^"]+)"', data)
                if sft_m and post_m:
                    return {
                        "urlPost": post_m.group(1),
                        "ppft": quote(sft_m.group(1), safe="-*"),
                    }

            # MSAAUTH is enough to continue — polish can establish AMC via cookie SSO
            logging.warning(
                "MSAAUTH present for %s but no urlPost after redirects — cookies-only polish",
                email,
            )
            return {"_cookies_only": True}

        sft_match = re.search(r'"sFT"\s*:\s*"([^"]+)"', loginData.text)
        if not sft_match:
            data = await handle_redirects(session, loginData.text)
            if isinstance(data, dict) and data.get("urlPost"):
                return data
            if isinstance(data, dict) and data.get("_cookies_only"):
                return data
            # Prefer real OTP/login errors over HTML lock false-positives
            err = re.search(r'"sErrTxt"\s*:\s*"((?:\\.|[^"])*)"', loginData.text)
            if err:
                txt = re.sub(r"<[^>]+>", "", err.group(1)).replace('\\"', '"')
                if txt.strip():
                    return {"_error": txt.strip()[:200]}
            lock_reason = await get_account_lock_reason(email, None)
            if lock_reason:
                return {"_error": lock_reason}
            logging.warning(
                "MSAAUTH present for %s but no sFT — cookies-only polish",
                email,
            )
            return {"_cookies_only": True}

        ppft = quote(sft_match.group(1), safe='-*')

        return {
            "urlPost" : urlPost.group(1),
            "ppft": ppft
        }

    # Prefer explicit login error text over HTML lock heuristics
    err = re.search(r'"sErrTxt"\s*:\s*"((?:\\.|[^"])*)"', loginData.text)
    if err:
        txt = re.sub(r"<[^>]+>", "", err.group(1)).replace('\\"', '"').strip()
        if txt:
            return {"_error": txt[:200]}

    lock_reason = await get_account_lock_reason(email, loginData.text)
    if lock_reason:
        return {"_error": lock_reason}
    return {"_error": "Login failed — no MSAAUTH cookie (wrong/expired OTP or Microsoft rejected login)."}
