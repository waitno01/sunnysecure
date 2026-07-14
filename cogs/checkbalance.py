from discord.ext import commands
import discord
import json

from payments.ltc_wallet import get_ltc_wallet, get_ltc_usd_rate

bot_config = json.load(open("config/bot.json", "r"))
name = bot_config["enabled_commands"]["aliases"]["checkbalance"]


class CheckBalance(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(
        name=name,
        description="Check the Litecoin hot-wallet balance (USD + LTC)",
    )
    async def checkbalance(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        try:
            wallet = get_ltc_wallet()
            snap = wallet.balance_snapshot()
            ltc = float(snap["ltc"])
            rate = float(snap["rate"] or 0) or get_ltc_usd_rate()
            usd = float(snap["usd"]) if snap.get("usd") is not None else ltc * rate
            embed = discord.Embed(
                title="LTC Hot Wallet Balance",
                color=0x345D9D,
            )
            embed.add_field(name="USD", value=f"**${usd:.2f}**", inline=True)
            embed.add_field(name="LTC", value=f"**{ltc:.8f}**", inline=True)
            embed.add_field(name="Rate", value=f"${rate:.2f}/LTC", inline=True)
            embed.add_field(name="Address", value=f"`{wallet.address}`", inline=False)
            await ctx.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            await ctx.followup.send(
                f"Could not fetch wallet balance.\n```{exc}```",
                ephemeral=True,
            )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(CheckBalance(bot))
