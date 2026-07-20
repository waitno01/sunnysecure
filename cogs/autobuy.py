from discord.ext import commands, tasks
import discord
import json
import logging

from ui.buttons.autobuy import AutobuyView, build_autobuy_embed, refresh_autobuy_panels
from ui.modals.autobuy import _dm_owners
from payments.ltc_wallet import get_ltc_wallet
from database.database import DBConnection
from securing.autobuy_hold_check import process_due_hold_checks

bot_config = json.load(open("config/bot.json", "r"))
name = bot_config["enabled_commands"]["aliases"]["autobuy"]
logger = logging.getLogger("bot")

# 5 hours 50 minutes
_DEFAULT_LOCK_SECOND_HOURS = 5.0 + 50.0 / 60.0


def _autobuy_cfg() -> dict:
    with open("config/config.json", "r") as f:
        return json.load(f).get("autobuy") or {}


class Autobuy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._balance_watch.start()
        self._hold_check.start()

    def cog_unload(self):
        self._balance_watch.cancel()
        self._hold_check.cancel()

    @tasks.loop(seconds=15)
    async def _balance_watch(self):
        """Poll explorer/hot wallet and rewrite panel embeds when LTC balance changes."""
        try:
            await refresh_autobuy_panels(self.bot)
        except Exception:
            logger.exception("autobuy balance watch failed")

    @_balance_watch.before_loop
    async def _before_balance_watch(self):
        await self.bot.wait_until_ready()
        try:
            await refresh_autobuy_panels(self.bot, force=True)
        except Exception:
            logger.exception("autobuy initial panel refresh failed")

    @tasks.loop(minutes=15)
    async def _hold_check(self):
        """Every 15m: grace-only validity (2h) + lock (6h then +5h50m); clear after grace."""
        cfg = _autobuy_cfg()
        if cfg.get("hold_check_enabled", True) is False:
            return
        sec_interval = float(cfg.get("security_email_check_interval_hours") or 2)
        lock_interval = float(cfg.get("hold_check_interval_hours") or 6)
        lock_second = float(
            cfg.get("hold_check_second_interval_hours") or _DEFAULT_LOCK_SECOND_HOURS
        )
        try:
            result = await process_due_hold_checks(
                security_interval_hours=sec_interval,
                lock_interval_hours=lock_interval,
                lock_second_interval_hours=lock_second,
                limit=20,
            )
        except Exception:
            logger.exception("autobuy hold check loop failed")
            return

        stats = result.get("stats") or {}
        if (
            stats.get("checked")
            or stats.get("voided")
            or stats.get("cleared")
            or stats.get("sec_checked")
            or stats.get("lock_checked")
            or stats.get("partial")
        ):
            logger.info(
                "autobuy hold check: checked=%s sec=%s lock=%s partial=%s cleared=%s "
                "voided=%s rescheduled=%s skipped=%s",
                stats.get("checked", 0),
                stats.get("sec_checked", 0),
                stats.get("lock_checked", 0),
                stats.get("partial", 0),
                stats.get("cleared", 0),
                stats.get("voided", 0),
                stats.get("rescheduled", 0),
                stats.get("skipped", 0),
            )

        for ev in result.get("void_events") or []:
            await self._dm_void(ev)

        for ev in result.get("partial_events") or []:
            await self._dm_partial(ev)

    @_hold_check.before_loop
    async def _before_hold_check(self):
        await self.bot.wait_until_ready()

    async def _dm_void(self, ev: dict) -> None:
        """Account invalid during grace — DM seller + owners."""
        email = ev.get("email") or "?"
        reason = ev.get("reason") or "unknown"
        amount = float(ev.get("amount_usd") or 0)
        seller_id = ev.get("discord_id")
        credit_id = ev.get("credit_id")
        available = ev.get("available_at") or "unknown"

        seller_embed = discord.Embed(
            title="Credit voided — account failed hold check",
            description=(
                f"Account `{email}` failed a post-sale security check.\n"
                f"**Amount removed:** ${amount:.2f}\n"
                f"**Reason:** {reason}\n\n"
                "Credits only become withdrawable after the hold period **and** "
                "passing periodic security-email + Microsoft lock checks."
            ),
            color=0xE74C3C,
        )

        owner_embed = discord.Embed(
            title="Autobuy voided — invalid during grace",
            description=(
                f"**Seller:** <@{seller_id}>\n"
                f"**Account:** `{email}`\n"
                f"**Credit ID:** `{credit_id}`\n"
                f"**Amount removed:** ${amount:.2f}\n"
                f"**Reason:** {reason}\n"
                f"**Grace was until:** `{available}`\n\n"
                "Credit voided while still in the pending grace window."
            ),
            color=0xE74C3C,
        )

        try:
            user = self.bot.get_user(seller_id)
            if user is None:
                user = await self.bot.fetch_user(seller_id)
            await user.send(embed=seller_embed)
        except Exception:
            logger.exception(
                "Failed to DM void notice to seller %s for %s",
                seller_id,
                email,
            )

        try:
            await _dm_owners(self.bot, embeds=[owner_embed])
        except Exception:
            logger.exception(
                "Failed to DM owners about void credit=%s email=%s",
                credit_id,
                email,
            )

    async def _dm_partial(self, ev: dict) -> None:
        """RC invalid but security email still OK — alert seller + owners, keep holding."""
        email = ev.get("email") or "?"
        detail = ev.get("detail") or "Recovery code invalid; security email still present"
        amount = float(ev.get("amount_usd") or 0)
        available = ev.get("available_at") or "unknown"
        credit_id = ev.get("credit_id")
        seller_id = ev.get("discord_id")

        seller_embed = discord.Embed(
            title="Partial hold warning — recovery code invalid",
            description=(
                f"Account `{email}` failed the recovery-code check, but our security "
                f"email is **still present** on the account.\n\n"
                f"**Detail:** {detail}\n"
                f"**Pending credit:** ${amount:.2f}\n"
                f"**Grace ends:** `{available}`\n\n"
                "Your credit is **still holding** (not voided). "
                "If the buyer pulls the account fully (security email removed), "
                "the credit will be voided on a later check."
            ),
            color=0xF1C40F,
        )

        owner_embed = discord.Embed(
            title="Autobuy partial — RC bad, security email OK",
            description=(
                f"**Seller:** <@{seller_id}>\n"
                f"**Account:** `{email}`\n"
                f"**Credit ID:** `{credit_id}`\n"
                f"**Amount:** ${amount:.2f}\n"
                f"**RC source:** `{ev.get('rc_source') or 'unknown'}`\n"
                f"**Detail:** {detail}\n"
                f"**Grace ends:** `{available}`\n\n"
                "Credit remains in hold (not voided). Validity checks continue "
                "during grace; void only if security email is also gone."
            ),
            color=0xF1C40F,
        )

        # Seller
        try:
            user = self.bot.get_user(seller_id)
            if user is None:
                user = await self.bot.fetch_user(seller_id)
            await user.send(embed=seller_embed)
        except Exception:
            logger.exception(
                "Failed to DM partial notice to seller %s for %s",
                seller_id,
                email,
            )

        # Owners
        try:
            await _dm_owners(self.bot, embeds=[owner_embed])
        except Exception:
            logger.exception(
                "Failed to DM owners about partial credit=%s email=%s",
                credit_id,
                email,
            )

    @discord.slash_command(name=name, description="Post the account selling (autobuy) panel")
    async def autobuy(self, ctx: discord.ApplicationContext):
        if ctx.author.id not in self.bot.admins:
            await ctx.respond(
                "You do not have permission to execute this command!",
                ephemeral=True,
            )
            return

        try:
            wallet = get_ltc_wallet()
            wallet_note = f"Hot wallet deposit address:\n```{wallet.address}```"
        except Exception as exc:
            wallet_note = f"Wallet init warning: `{exc}`"

        await ctx.defer(ephemeral=True)
        embed = build_autobuy_embed()
        view = AutobuyView()
        msg = await ctx.channel.send(embed=embed, view=view)
        with DBConnection() as db:
            db.autobuy_upsert_panel(msg.id, msg.channel.id, getattr(ctx.guild, "id", None))
        await ctx.followup.send(
            f"Autobuy panel posted.\n{wallet_note}",
            ephemeral=True,
        )


def setup(bot):
    bot.add_cog(Autobuy(bot))
