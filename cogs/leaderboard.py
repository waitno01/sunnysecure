from datetime import datetime
import json

from discord.ext import commands
import discord

from database.database import DBConnection

bot_config = json.load(open("config/bot.json", "r"))
name = bot_config["enabled_commands"]["aliases"]["leaderboard"]


class Leaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(
        name=name,
        description="Top MFA sellers by accounts sold and $ paid",
    )
    async def leaderboard(
        self,
        ctx: discord.ApplicationContext,
        limit: discord.Option(int, "How many sellers to show", required=False, default=10, min_value=1, max_value=25) = 10,
    ):
        await ctx.defer()
        with DBConnection() as db:
            rows = db.autobuy_leaderboard(limit)

        if not rows:
            await ctx.followup.send("No successful sells yet.")
            return

        lines = []
        for i, row in enumerate(rows, start=1):
            uid = row["discord_id"]
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"`#{i}`")
            lines.append(
                f"{medal} <@{uid}> — **{row['mfa_sold']}** MFA · "
                f"**${row['total_paid_usd']:.2f}** paid"
            )

        embed = discord.Embed(
            title="Seller Leaderboard",
            description="\n".join(lines),
            color=0x2B2D31,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=f"Top {len(rows)} by MFA sold")
        await ctx.followup.send(embed=embed)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Leaderboard(bot))
