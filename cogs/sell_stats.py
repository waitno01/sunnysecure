from datetime import datetime
import json

from discord.ext import commands
import discord

from database.database import DBConnection

bot_config = json.load(open("config/bot.json", "r"))
name = bot_config["enabled_commands"]["aliases"]["sell_stats"]


class SellStats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(
        name=name,
        description="View MFA selling stats (sold count + $ paid)",
    )
    async def sell_stats(
        self,
        ctx: discord.ApplicationContext,
        user: discord.Option(
            discord.Member,
            "Seller to look up (defaults to you)",
            required=False,
        ) = None,
    ):
        target = user or ctx.author
        await ctx.defer()

        with DBConnection() as db:
            stats = db.autobuy_seller_stats(target.id)

        embed = discord.Embed(
            title=f"Seller stats — {target.display_name}",
            color=0x2B2D31,
            timestamp=datetime.utcnow(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name="MFA sold",
            value=f"**{stats['mfa_sold']}**",
            inline=True,
        )
        embed.add_field(
            name="Total paid",
            value=f"**${stats['total_paid_usd']:.2f}**",
            inline=True,
        )
        embed.add_field(
            name="Failed submits",
            value=f"**{stats['mfa_failed']}**",
            inline=True,
        )
        embed.add_field(
            name="Balance",
            value=(
                f"Available: **${stats['available_usd']:.2f}**\n"
                f"Pending: **${stats['pending_usd']:.2f}**\n"
                f"Withdrawn: **${stats['withdrawn_usd']:.2f}**"
            ),
            inline=False,
        )
        embed.set_footer(text=f"User ID {target.id}")
        await ctx.followup.send(embed=embed)


def setup(bot: commands.Bot) -> None:
    bot.add_cog(SellStats(bot))
