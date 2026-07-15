from datetime import datetime, timedelta, timezone
import json
import logging

from discord import ui
import discord

from database.database import DBConnection
from payments.ltc_wallet import is_valid_ltc_address
from securing.recovery_secure import recovery_secure

logger = logging.getLogger("bot")


def _autobuy_cfg() -> dict:
    with open("config/config.json", "r") as f:
        return json.load(f).get("autobuy") or {}


def _owner_ids() -> list[int]:
    try:
        with open("config/config.json", "r") as f:
            raw = json.load(f).get("owners") or []
        return [int(x) for x in raw]
    except Exception:
        logger.exception("Failed to load owner ids")
        return []


def _logs_channel_id() -> int | None:
    try:
        with open("config/config.json", "r") as f:
            ch = (json.load(f).get("discord") or {}).get("logs_channel")
        return int(ch) if ch else None
    except Exception:
        return None


async def _dm_owners(
    client: discord.Client,
    *,
    embeds: list[discord.Embed] | None = None,
    content: str | None = None,
    guild: discord.Guild | None = None,
) -> None:
    owners = _owner_ids()
    if not owners or (not embeds and not content):
        return

    payload: dict = {}
    if content:
        payload["content"] = content
    if embeds:
        # Copy embeds so Discord doesn't choke on reused objects
        payload["embeds"] = [
            discord.Embed.from_dict(e.to_dict()) if hasattr(e, "to_dict") else e
            for e in embeds[:10]
        ]

    delivered = 0
    for oid in owners:
        try:
            user = client.get_user(oid)
            if user is None:
                user = await client.fetch_user(oid)

            # Prefer explicit DM channel creation (more reliable than User.send)
            try:
                dm = user.dm_channel or await user.create_dm()
                await dm.send(**payload)
                delivered += 1
                logger.info("autobuy owner DM ok → %s", oid)
                continue
            except discord.Forbidden:
                logger.warning("autobuy owner DM Forbidden for %s — trying guild member", oid)
            except discord.HTTPException as exc:
                logger.warning("autobuy owner DM HTTP %s for %s — trying guild member", exc, oid)

            # Fallback: Member.send via a mutual guild
            member = None
            if guild is not None:
                member = guild.get_member(oid)
                if member is None:
                    try:
                        member = await guild.fetch_member(oid)
                    except discord.HTTPException:
                        member = None
            if member is None:
                for g in getattr(client, "guilds", []) or []:
                    member = g.get_member(oid)
                    if member:
                        break
            if member is not None:
                await member.send(**payload)
                delivered += 1
                logger.info("autobuy owner DM ok via guild member → %s", oid)
            else:
                logger.error("autobuy owner DM failed — no reachable member for %s", oid)
        except Exception:
            logger.exception("Failed to DM owner %s autobuy notification", oid)

    # Mirror to logs channel so nothing is silently lost
    if delivered == 0:
        logs_id = _logs_channel_id()
        if logs_id and client:
            try:
                channel = client.get_channel(logs_id) or await client.fetch_channel(logs_id)
                mirror = dict(payload)
                if mirror.get("content"):
                    mirror["content"] = f"(owner DM failed) {mirror['content']}"
                else:
                    mirror["content"] = "(owner DM failed — mirrored here)"
                await channel.send(**mirror)
                logger.info("autobuy owner notify mirrored to logs channel %s", logs_id)
            except Exception:
                logger.exception("Failed to mirror autobuy notify to logs channel")


async def _notify_owners_submit_started(
    interaction: discord.Interaction,
    *,
    lines: list[str],
    price: float,
    ltc: str | None,
) -> None:
    """Immediate owner ping when a seller submits — before securing starts."""
    if not interaction.client:
        return
    seller = interaction.user
    emails = []
    for line in lines:
        parts = line.split(":", 1)
        emails.append(parts[0].strip() if parts else line[:40])

    embed = discord.Embed(
        title="📥 Autobuy — Sell submitted (processing…)",
        description=(
            f"**Seller:** {seller.mention} (`{seller.id}`)\n"
            f"**Name:** {getattr(seller, 'display_name', seller.name)}\n"
            f"**Server:** {interaction.guild.name if interaction.guild else 'unknown'}\n"
            f"**Accounts in batch:** **{len(lines)}** · **${price:.2f}** each"
        ),
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
    body = "\n".join(f"`{e}`" for e in emails[:15])
    if len(emails) > 15:
        body += f"\n… +{len(emails) - 15} more"
    embed.add_field(name="Emails submitted", value=body or "—", inline=False)
    if ltc:
        embed.add_field(name="Seller LTC", value=f"`{ltc}`", inline=False)
    embed.set_footer(text="You will get another DM per success + a batch summary when done.")
    await _dm_owners(
        interaction.client,
        embeds=[embed],
        guild=interaction.guild,
    )


def _owner_hit_embed(
    *,
    seller: discord.abc.User,
    submitted_email: str,
    account: dict,
    price: float,
    pending_hours: int,
    credit_id: int,
    guild: discord.Guild | None,
) -> discord.Embed:
    ms = {}
    mc = account.get("minecraft") or {}
    details = account.get("details") or {}
    # Prefer live fields from stored account payload if present
    # build_account_embeds returns microsoft under nested details text; hit_embed has creds
    hit = account.get("hit_embed")
    account_id = account.get("account_id") or "—"

    # Pull credential fields from the hit embed when possible via details string
    account_details = details.get("account_details") or ""
    # Also try reading from secured account structure if ever attached
    if isinstance(account.get("microsoft"), dict):
        ms = account["microsoft"]

    embed = discord.Embed(
        title="🛒 Autobuy — New MFA sold",
        description=(
            f"**Seller:** {seller.mention} (`{seller.id}`)\n"
            f"**Display:** {getattr(seller, 'display_name', seller.name)}\n"
            f"**Server:** {guild.name if guild else 'DM / unknown'}"
        ),
        color=0x57F287,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Submitted email", value=f"```{submitted_email}```", inline=False)
    embed.add_field(name="Payout", value=f"**${price:.2f}** pending **{pending_hours}h**", inline=True)
    embed.add_field(name="Credit ID", value=f"`{credit_id}`", inline=True)
    embed.add_field(name="Account ID", value=f"`{account_id}`", inline=True)

    if ms:
        embed.add_field(name="Primary email", value=f"```{ms.get('email', '—')}```", inline=False)
        embed.add_field(name="Security email", value=f"```{ms.get('security_email', '—')}```", inline=True)
        embed.add_field(name="Password", value=f"```{ms.get('password', '—')}```", inline=True)
        embed.add_field(name="Recovery code", value=f"```{ms.get('recovery_code', '—')}```", inline=False)
        if ms.get("auth_secret"):
            embed.add_field(name="Auth secret", value=f"```{ms.get('auth_secret')}```", inline=False)
        name_bits = []
        if ms.get("fullName") and ms.get("fullName") not in ("Failed to Get", "—"):
            name_bits.append(str(ms["fullName"]))
        if ms.get("region") and ms.get("region") not in ("Failed to Get", "—"):
            name_bits.append(str(ms["region"]))
        if ms.get("birthday") and ms.get("birthday") not in ("Failed to Get", "—"):
            name_bits.append(f"🎂 {ms['birthday']}")
        if name_bits:
            embed.add_field(name="Profile", value=" · ".join(name_bits), inline=False)
        embed.add_field(
            name="Minecraft",
            value=(
                f"```{mc.get('name') or 'No Minecraft'}```\n"
                f"Gamertag: `{mc.get('gamertag') or '—'}` · "
                f"Method: `{mc.get('method') or '—'}` · "
                f"Capes: `{mc.get('capes') or '—'}`"
            ),
            inline=False,
        )
    elif account_details:
        embed.add_field(name="Account details", value=account_details[:1020], inline=False)
    elif hit is not None:
        # Fall back: note that full hit embed is attached separately
        embed.add_field(
            name="Credentials",
            value="_Full hit details attached below._",
            inline=False,
        )

    embed.set_footer(text=f"Seller @{getattr(seller, 'name', seller.id)}")
    avatar = getattr(seller, "display_avatar", None)
    if avatar is not None:
        embed.set_thumbnail(url=avatar.url)
    return embed


async def _notify_owners_hit(
    interaction: discord.Interaction,
    *,
    submitted_email: str,
    account: dict,
    price: float,
    pending_hours: int,
    credit_id: int,
) -> None:
    if not interaction.client:
        return

    # Enrich with full secured payload from DB when available
    account_id = account.get("account_id")
    if account_id and not isinstance(account.get("microsoft"), dict):
        try:
            with DBConnection() as db:
                row = db.get_secured_account(account_id)
            if row:
                account = {
                    **account,
                    "microsoft": {
                        "email": row.get("ms_email"),
                        "security_email": row.get("ms_security_email"),
                        "password": row.get("ms_password"),
                        "recovery_code": row.get("ms_recovery_code"),
                        "auth_secret": row.get("ms_auth_secret"),
                        "fullName": row.get("ms_full_name"),
                        "region": row.get("ms_region"),
                        "birthday": row.get("ms_birthday"),
                    },
                    "minecraft": {
                        "name": row.get("mc_name"),
                        "method": row.get("mc_method"),
                        "gamertag": row.get("mc_gamertag"),
                        "capes": row.get("mc_capes"),
                        "SSID": row.get("mc_ssid"),
                    },
                }
        except Exception:
            logger.exception("Could not load secured account %s for owner DM", account_id)

    notice = _owner_hit_embed(
        seller=interaction.user,
        submitted_email=submitted_email,
        account=account,
        price=price,
        pending_hours=pending_hours,
        credit_id=credit_id,
        guild=interaction.guild,
    )
    embeds = [notice]
    hit = account.get("hit_embed")
    if hit is not None:
        embeds.append(hit)
    await _dm_owners(interaction.client, embeds=embeds, guild=interaction.guild)


async def _notify_owners_batch_summary(
    interaction: discord.Interaction,
    *,
    hits: int,
    fails: int,
    earned: float,
    details: list[str],
    sold_today: int,
    max_day: int,
) -> None:
    """Always notify owners when a sell submit finishes (even all-fail)."""
    if not interaction.client:
        return
    seller = interaction.user
    color = 0x57F287 if hits else 0xED4245
    embed = discord.Embed(
        title="📋 Autobuy — Sell submit finished",
        description=(
            f"**Seller:** {seller.mention} (`{seller.id}`)\n"
            f"**Name:** {getattr(seller, 'display_name', seller.name)}\n"
            f"**Server:** {interaction.guild.name if interaction.guild else 'unknown'}"
        ),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="✅ Success", value=str(hits), inline=True)
    embed.add_field(name="❌ Failed", value=str(fails), inline=True)
    embed.add_field(name="💵 Credited", value=f"${earned:.2f}", inline=True)
    embed.add_field(
        name="Seller day limit",
        value=f"**{sold_today}/{max_day}** sold today",
        inline=False,
    )
    if details:
        body = "\n".join(details)
        if len(body) > 1000:
            body = body[:997] + "..."
        embed.add_field(name="Per-account results", value=body, inline=False)
    await _dm_owners(interaction.client, embeds=[embed], guild=interaction.guild)


async def _grant_seller_role(interaction: discord.Interaction) -> None:
    """Assign the configured seller role after a successful MFA sell."""
    role_raw = _autobuy_cfg().get("seller_role_id")
    if not role_raw:
        return
    try:
        role_id = int(role_raw)
    except (TypeError, ValueError):
        return

    guild = interaction.guild
    if guild is None:
        return

    member = interaction.user
    if not isinstance(member, discord.Member):
        try:
            member = await guild.fetch_member(interaction.user.id)
        except discord.HTTPException:
            return

    if any(r.id == role_id for r in member.roles):
        return

    role = guild.get_role(role_id)
    if role is None:
        return

    try:
        await member.add_roles(role, reason="Successful MFA sell")
    except discord.HTTPException:
        logger.exception(
            "Failed to grant seller role %s to %s",
            role_id,
            interaction.user.id,
        )


async def _send_seller_success_dm(
    user: discord.abc.User,
    *,
    hits: int,
    fails: int,
    earned: float,
    price: float,
    pending_hours: int,
    unlock_ts: int | None,
    bals: dict,
    sold_today: int,
    max_day: int,
    details: list[str],
) -> None:
    """Fancy payout receipt DM after successful MFA sells."""
    if unlock_ts is None:
        unlock_ts = int(
            (datetime.now(timezone.utc) + timedelta(hours=pending_hours)).timestamp()
        )

    noun = "account" if hits == 1 else "accounts"
    embed = discord.Embed(
        title="Sale Confirmed",
        description=(
            f"**{hits}** {noun} successfully secured.\n"
            f"You earned **${earned:.2f}** "
            f"({hits} × ${price:.2f})."
        ),
        color=0x57F287,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Accounts Secured", value=f"**{hits}**", inline=True)
    embed.add_field(name="Total Earned", value=f"**${earned:.2f}**", inline=True)
    if fails:
        embed.add_field(name="Failed", value=f"**{fails}**", inline=True)

    embed.add_field(
        name="Payout Unlock",
        value=(
            f"Credits unlock <t:{unlock_ts}:R> after hold **and** "
            f"passing lock/pullback checks.\n"
            f"<t:{unlock_ts}:F>\n"
            f"_Each credit has its own {pending_hours}h timer._"
        ),
        inline=False,
    )
    embed.add_field(
        name="Wallet",
        value=(
            f"Available · **${bals['available_usd']:.2f}**\n"
            f"Pending · **${bals['pending_usd']:.2f}**\n"
            f"Sold today · **{sold_today}/{max_day}**"
        ),
        inline=False,
    )

    success_lines = [d for d in details if "— +$" in d]
    if success_lines:
        body = "\n".join(success_lines)
        if len(body) > 900:
            body = body[:897] + "..."
        embed.add_field(name="Secured", value=body, inline=False)

    embed.set_footer(text="Account Selling Service • Withdraw after unlock")

    try:
        await user.send(embed=embed)
    except discord.HTTPException:
        logger.warning("Could not DM sell receipt to user %s", getattr(user, "id", "?"))


class LinkLtcModal(ui.Modal):
    def __init__(self, current_address: str | None = None):
        self.current_address = (current_address or "").strip() or None
        title = "Update LTC Address" if self.current_address else "Link LTC Address"
        super().__init__(title=title)
        placeholder = "L... / M... / ltc1... (replaces your current address)"
        if self.current_address:
            shown = self.current_address
            if len(shown) > 28:
                shown = f"{shown[:12]}…{shown[-8:]}"
            placeholder = f"Current: {shown} — paste new address to replace"
        self.add_item(ui.InputText(
            label="Your Litecoin (LTC) address",
            style=discord.InputTextStyle.short,
            placeholder=placeholder[:100],
            required=True,
            max_length=100,
        ))

    async def callback(self, interaction: discord.Interaction):
        # Normalize: strip whitespace / zero-width chars that break validation
        raw = self.children[0].value or ""
        address = "".join(raw.split())
        address = address.replace("\u200b", "").replace("\ufeff", "").strip()
        # Bech32 is case-insensitive — store lowercase for ltc1
        if address.lower().startswith("ltc1"):
            address = address.lower()

        if not is_valid_ltc_address(address):
            await interaction.response.send_message(
                "Invalid Litecoin address. Use a mainnet address starting with `L`, `M`, or `ltc1`.",
                ephemeral=True,
            )
            return

        with DBConnection() as db:
            previous = db.autobuy_get_ltc(interaction.user.id)
            db.autobuy_set_ltc(interaction.user.id, address)
            # Read back to confirm persist
            saved = db.autobuy_get_ltc(interaction.user.id)

        if saved != address:
            await interaction.response.send_message(
                "Failed to save LTC address — please try again.",
                ephemeral=True,
            )
            return

        if previous and previous != address:
            embed = discord.Embed(
                title="LTC Address Updated",
                description=(
                    f"**Previous:**\n```{previous}```\n"
                    f"**New (active):**\n```{address}```\n"
                    "Future withdrawals will use the new address."
                ),
                color=0x57F287,
            )
        elif previous and previous == address:
            embed = discord.Embed(
                title="LTC Already Linked",
                description=f"Same address kept:\n```{address}```",
                color=0x57F287,
            )
        else:
            embed = discord.Embed(
                title="LTC Linked",
                description=f"Payouts will be sent to:\n```{address}```",
                color=0x57F287,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class WithdrawModal(ui.Modal):
    def __init__(self, available_usd: float):
        super().__init__(title="Withdraw Balance")
        self.available_usd = available_usd
        self.add_item(ui.InputText(
            label="USD amount to withdraw",
            style=discord.InputTextStyle.short,
            placeholder=f"Available: ${available_usd:.2f}  |  Example: 10",
            required=True,
            max_length=16,
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        raw = (self.children[0].value or "").strip().replace("$", "")
        try:
            amount = float(raw)
        except ValueError:
            await interaction.followup.send("Enter a valid USD number.", ephemeral=True)
            return

        cfg = _autobuy_cfg()
        min_withdraw = float(cfg.get("min_withdraw_usd") or 1.0)
        if amount < min_withdraw:
            await interaction.followup.send(
                f"Minimum withdraw is **${min_withdraw:.2f}**.",
                ephemeral=True,
            )
            return

        with DBConnection() as db:
            ltc = db.autobuy_get_ltc(interaction.user.id)
            bals = db.autobuy_balances(interaction.user.id)

        if not ltc:
            await interaction.followup.send(
                "Link an LTC address first using **Link LTC**.",
                ephemeral=True,
            )
            return

        if amount > bals["available_usd"] + 1e-9:
            await interaction.followup.send(
                f"Insufficient available balance. Available: **${bals['available_usd']:.2f}** "
                f"(pending: **${bals['pending_usd']:.2f}** — each credit unlocks 24h after earn).",
                ephemeral=True,
            )
            return

        with DBConnection() as db:
            taken = db.autobuy_consume_credits(interaction.user.id, amount)
            if not taken:
                await interaction.followup.send(
                    "Could not reserve credits (balance may have changed). Try again.",
                    ephemeral=True,
                )
                return
            wid = db.autobuy_add_withdrawal(
                interaction.user.id,
                amount,
                None,
                ltc,
                status="sending",
            )

        try:
            from payments.ltc_wallet import get_ltc_usd_rate, get_ltc_wallet

            rate = get_ltc_usd_rate()
            amount_ltc = amount / rate
            # dust / precision
            amount_ltc = round(amount_ltc, 8)
            if amount_ltc < 0.0001:
                raise RuntimeError("Withdrawal LTC amount too small after conversion")

            wallet = get_ltc_wallet()
            txid = wallet.send_ltc(ltc, amount_ltc)

            with DBConnection() as db:
                db.autobuy_update_withdrawal(
                    wid, status="sent", txid=txid, amount_ltc=amount_ltc
                )

            from payments.ltc_wallet import blockcypher_tx_url

            explorer = blockcypher_tx_url(txid)
            embed = discord.Embed(
                title="Withdrawal Sent",
                description=(
                    f"**${amount:.2f}** → **{amount_ltc:.8f} LTC**\n"
                    f"**To:** `{ltc}`\n"
                    f"**TXID:** `{txid}`\n"
                    f"[View on BlockCypher]({explorer})"
                ),
                color=0x57F287,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

            # Also DM the seller a receipt
            try:
                dm = discord.Embed(
                    title="Withdrawal successful",
                    description=(
                        f"Your payout was sent.\n\n"
                        f"**Amount:** ${amount:.2f} ({amount_ltc:.8f} LTC)\n"
                        f"**Address:** `{ltc}`\n"
                        f"**TXID:** `{txid}`\n"
                        f"[BlockCypher]({explorer})"
                    ),
                    color=0x57F287,
                )
                await interaction.user.send(embed=dm)
            except discord.HTTPException:
                logger.warning(
                    "Could not DM withdraw receipt to %s", interaction.user.id
                )

            # Hot wallet balance dropped — refresh all selling panels
            try:
                from ui.buttons.autobuy import refresh_autobuy_panels

                await refresh_autobuy_panels(interaction.client, force=True)
            except Exception:
                logger.exception("Failed to refresh autobuy panels after withdraw")
        except Exception as exc:
            logger.exception("autobuy withdraw failed for %s", interaction.user.id)
            # refund credits
            with DBConnection() as db:
                db.autobuy_refund_credits(taken)
                db.autobuy_update_withdrawal(
                    wid, status="failed", error=str(exc)[:500]
                )

            await interaction.followup.send(
                f"Withdrawal failed — balance was restored.\n```{exc}```",
                ephemeral=True,
            )


class SellMfaModal(ui.Modal):
    def __init__(self):
        cfg = _autobuy_cfg()
        max_lines = int(cfg.get("max_accounts_per_submit") or 10)
        super().__init__(title="Sell MFA")
        self.add_item(ui.InputText(
            label=f"Accounts (email:recoverycode, max {max_lines})",
            style=discord.InputTextStyle.long,
            placeholder="email1@outlook.com:XXXXX-XXXXX-XXXXX-XXXXX-XXXXX\nemail2@outlook.com:YYYYY-...",
            required=True,
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cfg = _autobuy_cfg()
        price = float(cfg.get("price_per_mfa") or 5.0)
        max_lines = int(cfg.get("max_accounts_per_submit") or 10)
        max_day = int(cfg.get("max_accounts_per_day") or 10)
        pending_hours = int(cfg.get("pending_hours") or 24)

        with DBConnection() as db:
            ltc = db.autobuy_get_ltc(interaction.user.id)
            sold_today = db.autobuy_sells_today(interaction.user.id)

        if not ltc:
            await interaction.followup.send(
                "You must **Link LTC** before selling MFA accounts.",
                ephemeral=True,
            )
            return

        remaining_today = max_day - sold_today
        if remaining_today <= 0:
            await interaction.followup.send(
                f"Daily sell limit reached (**{max_day}/day**). Try again tomorrow.",
                ephemeral=True,
            )
            return

        lines = []
        for raw in (self.children[0].value or "").splitlines():
            line = raw.strip()
            if line:
                lines.append(line)

        if not lines:
            await interaction.followup.send("No accounts provided.", ephemeral=True)
            return

        if len(lines) > max_lines:
            await interaction.followup.send(
                f"Maximum **{max_lines}** accounts per submit.",
                ephemeral=True,
            )
            return

        if len(lines) > remaining_today:
            await interaction.followup.send(
                f"You can only sell **{remaining_today}** more account(s) today "
                f"({sold_today}/{max_day} used).",
                ephemeral=True,
            )
            return

        status = discord.Embed(
            title="Sell MFA — Processing",
            description=f"Securing **{len(lines)}** account(s)…",
            color=0x5865F2,
        )
        msg = await interaction.followup.send(embed=status, ephemeral=True)

        try:
            await _notify_owners_submit_started(
                interaction,
                lines=lines,
                price=price,
                ltc=ltc,
            )
        except Exception:
            logger.exception("Failed to DM owners about autobuy submit start")

        hits = 0
        fails = 0
        details: list[str] = []
        earned = 0.0
        unlock_ts: int | None = None

        accounts_channel_id = None
        try:
            with open("config/config.json", "r") as f:
                conf = json.load(f)
            ch = conf.get("discord", {}).get("accounts_channel")
            if ch:
                accounts_channel_id = int(ch)
        except Exception:
            pass

        for line in lines:
            parts = line.split(":", 1)
            if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                fails += 1
                details.append(f"`{line[:40]}` — invalid format")
                continue

            email, recovery_code = parts[0].strip(), parts[1].strip()
            try:
                account = await recovery_secure(
                    email,
                    "rcode",
                    {"recovery_code": recovery_code},
                )
            except Exception as exc:
                logger.exception("autobuy sell failed for %s", email)
                fails += 1
                details.append(f"`{email}` — {exc.__class__.__name__}")
                with DBConnection() as db:
                    db.autobuy_record_sell(interaction.user.id, email, False)
                continue

            if account == "invalid" or (
                isinstance(account, dict) and account.get("failed")
            ):
                fails += 1
                reason = "invalid recovery code"
                if isinstance(account, dict):
                    reason = account.get("reason") or reason
                details.append(f"`{email}` — {reason}")
                with DBConnection() as db:
                    db.autobuy_record_sell(interaction.user.id, email, False)

                # Always DM seller new credentials when recover already changed them
                fail_embed = None
                if isinstance(account, dict):
                    # Never show post-secure primary (sunny@) to the seller
                    fail_embed = account.get("seller_embed") or account.get("hit_embed")
                    if fail_embed is None and account.get("credentials_changed"):
                        from securing.build_embeds import build_failure_embed

                        ms = account.get("microsoft") or {}
                        # Prefer original login email for seller-facing failure DM
                        seller_email = (
                            ms.get("original_email")
                            or email
                        )
                        fail_embed = build_failure_embed(
                            seller_email,
                            {
                                **ms,
                                # Force copy-line to use original, not new primary
                                "email": seller_email,
                            },
                            reason,
                            error=account.get("error") or reason,
                            credentials_changed=True,
                        )
                if fail_embed is not None:
                    try:
                        await interaction.user.send(embed=fail_embed)
                    except discord.HTTPException:
                        try:
                            await interaction.followup.send(embed=fail_embed, ephemeral=True)
                        except discord.HTTPException:
                            pass
                continue

            if not account or not isinstance(account, dict):
                fails += 1
                details.append(f"`{email}` — securing failed")
                with DBConnection() as db:
                    db.autobuy_record_sell(interaction.user.id, email, False)
                continue

            unlock_dt = datetime.now(timezone.utc) + timedelta(hours=pending_hours)
            available_at = unlock_dt.strftime("%Y-%m-%d %H:%M:%S")
            unlock_ts = int(unlock_dt.timestamp())
            check_hours = float(cfg.get("hold_check_interval_hours") or 6)
            next_check = (
                datetime.now(timezone.utc) + timedelta(hours=min(check_hours, pending_hours))
            ).strftime("%Y-%m-%d %H:%M:%S")

            with DBConnection() as db:
                credit_id = db.autobuy_add_credit(
                    interaction.user.id,
                    price,
                    available_at,
                    "sell_mfa",
                    email,
                    next_check_at=next_check,
                )
                db.autobuy_record_sell(
                    interaction.user.id,
                    email,
                    True,
                    credit_id,
                    account_id=account.get("account_id"),
                )

            hits += 1
            earned += price
            details.append(f"`{email}` — +${price:.2f} (pending {pending_hours}h)")

            # Notify accounts channel for owners (not the seller)
            if accounts_channel_id and interaction.client:
                try:
                    channel = interaction.client.get_channel(accounts_channel_id)
                    if channel is None:
                        channel = await interaction.client.fetch_channel(accounts_channel_id)
                    hit_embed = account.get("hit_embed")
                    if hit_embed and channel:
                        await channel.send(
                            content=f"Autobuy MFA sell by <@{interaction.user.id}>",
                            embed=hit_embed,
                        )
                except Exception:
                    logger.exception("Failed to post autobuy hit to accounts channel")

            try:
                await _notify_owners_hit(
                    interaction,
                    submitted_email=email,
                    account=account,
                    price=price,
                    pending_hours=pending_hours,
                    credit_id=credit_id,
                )
            except Exception:
                logger.exception("Failed to DM owners about autobuy hit")

        with DBConnection() as db:
            bals = db.autobuy_balances(interaction.user.id)
            sold_today = db.autobuy_sells_today(interaction.user.id)

        summary = discord.Embed(
            title="Sell MFA — Complete",
            color=0x57F287 if hits else 0xED4245,
        )
        summary.add_field(name="Success", value=str(hits), inline=True)
        summary.add_field(name="Failed", value=str(fails), inline=True)
        summary.add_field(name="Earned", value=f"${earned:.2f} pending", inline=True)
        summary.add_field(
            name="Balance",
            value=(
                f"Available: **${bals['available_usd']:.2f}**\n"
                f"Pending: **${bals['pending_usd']:.2f}**\n"
                f"Sold today: **{sold_today}/{max_day}**"
            ),
            inline=False,
        )
        if details:
            body = "\n".join(details)
            if len(body) > 1000:
                body = body[:997] + "..."
            summary.add_field(name="Details", value=body, inline=False)

        try:
            await msg.edit(embed=summary)
        except discord.HTTPException:
            await interaction.followup.send(embed=summary, ephemeral=True)

        try:
            await _notify_owners_batch_summary(
                interaction,
                hits=hits,
                fails=fails,
                earned=earned,
                details=details,
                sold_today=sold_today,
                max_day=max_day,
            )
        except Exception:
            logger.exception("Failed to DM owners autobuy batch summary")

        if hits > 0:
            await _grant_seller_role(interaction)
            await _send_seller_success_dm(
                interaction.user,
                hits=hits,
                fails=fails,
                earned=earned,
                price=price,
                pending_hours=pending_hours,
                unlock_ts=unlock_ts,
                bals=bals,
                sold_today=sold_today,
                max_day=max_day,
                details=details,
            )
