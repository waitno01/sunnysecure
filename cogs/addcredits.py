"""Owner-only command to grant withdrawable autobuy credits."""

from datetime import datetime
import json
import logging

from discord.ext import commands
import discord

from database.database import DBConnection

bot_config = json.load(open("config/bot.json", "r"))
name = bot_config["enabled_commands"]["aliases"]["addcredits"]
logger = logging.getLogger("bot")


class AddCredits(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(
        name=name,
        description="(Owner) Add withdrawable autobuy credits to a user",
    )
    async def addcredits(
        self,
        ctx: discord.ApplicationContext,
        user: discord.Option(discord.Member, "User who receives the credits"),
        amount: discord.Option(
            float,
            "USD amount to add",
            min_value=0.01,
            max_value=100000,
        ),
        note: discord.Option(
            str,
            "Optional note (stored with the credit)",
            required=False,
            max_length=180,
        ) = None,
    ):
        if ctx.author.id not in self.bot.admins:
            await ctx.respond(
                "You do not have permission to use this command.",
                ephemeral=True,
            )
            return

        amount = round(float(amount), 2)
        if amount <= 0:
            await ctx.respond("Amount must be greater than 0.", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)

        try:
            with DBConnection() as db:
                credit_id = db.autobuy_add_manual_credit(
                    user.id,
                    amount,
                    note=note,
                    added_by=ctx.author.id,
                )
                bals = db.autobuy_balances(user.id)
        except Exception as exc:
            logger.exception("addcredits failed for %s amount=%s", user.id, amount)
            await ctx.followup.send(
                f"Failed to add credits.\n```{exc}```",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Credits added",
            description=(
                f"Added **${amount:.2f}** to {user.mention} "
                f"(`{user.id}`).\n"
                f"**Credit ID:** `{credit_id}`\n"
                f"**Note:** {note or '—'}\n\n"
                f"**Their balances now**\n"
                f"Available: **${bals['available_usd']:.2f}**\n"
                f"Pending: **${bals['pending_usd']:.2f}**"
            ),
            color=0x57F287,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=f"Added by {ctx.author} ({ctx.author.id})")
        await ctx.followup.send(embed=embed, ephemeral=True)

        # Notify the recipient (best-effort)
        try:
            dm = discord.Embed(
                title="You received autobuy credits",
                description=(
                    f"An owner added **${amount:.2f}** to your withdrawable balance.\n"
                    + (f"**Note:** {note}\n" if note else "")
                    + f"\nAvailable now: **${bals['available_usd']:.2f}**"
                ),
                color=0x57F287,
            )
            await user.send(embed=dm)
        except Exception:
            logger.info("Could not DM credit recipient %s", user.id)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(AddCredits(bot))
