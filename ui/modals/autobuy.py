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


class LinkLtcModal(ui.Modal):
    def __init__(self):
        super().__init__(title="Link LTC Address")
        self.add_item(ui.InputText(
            label="Your Litecoin (LTC) address",
            style=discord.InputTextStyle.short,
            placeholder="Example: LTc1q... or LPvqR... (starts with L, M, or ltc1)",
            required=True,
            max_length=100,
        ))

    async def callback(self, interaction: discord.Interaction):
        address = (self.children[0].value or "").strip()
        if not is_valid_ltc_address(address):
            await interaction.response.send_message(
                "Invalid Litecoin address. Use a mainnet address starting with `L`, `M`, or `ltc1`.",
                ephemeral=True,
            )
            return

        with DBConnection() as db:
            db.autobuy_set_ltc(interaction.user.id, address)

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

            embed = discord.Embed(
                title="Withdrawal Sent",
                description=(
                    f"**${amount:.2f}** → **{amount_ltc:.8f} LTC**\n"
                    f"Address: `{ltc}`\n"
                    f"TX: `{txid}`"
                ),
                color=0x57F287,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
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

        hits = 0
        fails = 0
        details: list[str] = []
        earned = 0.0

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

                # DM seller new credentials + error when recovery already changed them
                fail_embed = None
                if isinstance(account, dict):
                    fail_embed = account.get("hit_embed")
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

            available_at = (
                datetime.now(timezone.utc) + timedelta(hours=pending_hours)
            ).strftime("%Y-%m-%d %H:%M:%S")

            with DBConnection() as db:
                credit_id = db.autobuy_add_credit(
                    interaction.user.id,
                    price,
                    available_at,
                    "sell_mfa",
                    email,
                )
                db.autobuy_record_sell(interaction.user.id, email, True, credit_id)

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
