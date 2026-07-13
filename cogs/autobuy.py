from discord.ext import commands
import discord
import json

from ui.buttons.autobuy import AutobuyView, build_autobuy_embed
from payments.ltc_wallet import get_ltc_wallet

bot_config = json.load(open("config/bot.json", "r"))
name = bot_config["enabled_commands"]["aliases"]["autobuy"]


class Autobuy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(name=name, description="Post the account selling (autobuy) panel")
    async def autobuy(self, ctx: discord.ApplicationContext):
        if ctx.author.id not in self.bot.admins:
            await ctx.respond(
                "You do not have permission to execute this command!",
                ephemeral=True,
            )
            return

        # Ensure hot wallet exists so owner can fund it
        try:
            wallet = get_ltc_wallet()
            wallet_note = f"Hot wallet deposit address:\n```{wallet.address}```"
        except Exception as exc:
            wallet_note = f"Wallet init warning: `{exc}`"

        await ctx.defer(ephemeral=True)
        await ctx.channel.send(
            embed=build_autobuy_embed(),
            view=AutobuyView(),
        )
        await ctx.followup.send(
            f"Autobuy panel sent.\n{wallet_note}",
            ephemeral=True,
        )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(Autobuy(bot))
