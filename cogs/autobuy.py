from discord.ext import commands, tasks
import discord
import json
import logging

from ui.buttons.autobuy import AutobuyView, build_autobuy_embed, refresh_autobuy_panels
from payments.ltc_wallet import get_ltc_wallet
from database.database import DBConnection
from securing.autobuy_hold_check import process_due_hold_checks

bot_config = json.load(open("config/bot.json", "r"))
name = bot_config["enabled_commands"]["aliases"]["autobuy"]
logger = logging.getLogger("bot")


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
        """Every 15m: due security-email (1h) and lock (6h) checks on holding credits."""
        cfg = _autobuy_cfg()
        if cfg.get("hold_check_enabled", True) is False:
            return
        sec_interval = float(cfg.get("security_email_check_interval_hours") or 1)
        lock_interval = float(cfg.get("hold_check_interval_hours") or 6)
        try:
            result = await process_due_hold_checks(
                security_interval_hours=sec_interval,
                lock_interval_hours=lock_interval,
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
        ):
            logger.info(
                "autobuy hold check: checked=%s sec=%s lock=%s cleared=%s voided=%s "
                "rescheduled=%s skipped=%s",
                stats.get("checked", 0),
                stats.get("sec_checked", 0),
                stats.get("lock_checked", 0),
                stats.get("cleared", 0),
                stats.get("voided", 0),
                stats.get("rescheduled", 0),
                stats.get("skipped", 0),
            )

        for ev in result.get("void_events") or []:
            await self._dm_void(ev)

    @_hold_check.before_loop
    async def _before_hold_check(self):
        await self.bot.wait_until_ready()

    async def _dm_void(self, ev: dict) -> None:
        try:
            user = self.bot.get_user(ev["discord_id"])
            if user is None:
                user = await self.bot.fetch_user(ev["discord_id"])
            embed = discord.Embed(
                title="Credit voided — account failed hold check",
                description=(
                    f"Account `{ev.get('email')}` failed a post-sale security check.\n"
                    f"**Amount removed:** ${float(ev.get('amount_usd') or 0):.2f}\n"
                    f"**Reason:** {ev.get('reason') or 'unknown'}\n\n"
                    "Credits only become withdrawable after the hold period **and** "
                    "passing periodic security-email + Microsoft lock checks."
                ),
                color=0xE74C3C,
            )
            await user.send(embed=embed)
        except Exception:
            logger.exception(
                "Failed to DM void notice to %s for %s",
                ev.get("discord_id"),
                ev.get("email"),
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
