from ui.buttons.link_account import LinkAccountView

from discord.ext import commands
import discord
import json

bot_config = json.load(open("config/bot.json", "r"))
name = bot_config["enabled_commands"]["aliases"]["send_embed"]

def get_embed() -> dict:
    with open("config/bot.json") as f:
        data = json.load(f)

    embed = data["embeds"]["verification"]["default"]
    return {
        "title": embed["title"],
        "description": embed["description"],
        "color": embed["color"],
        "ephemeral": data["ephemeral"],
    }
    
class sendEmbed(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    send = discord.SlashCommandGroup(name)
    @send.command(name="embed", description="Sends the verification embed")
    async def embed_command(self, ctx: discord.ApplicationContext):
        if ctx.author.id not in self.bot.admins:
            await ctx.respond(
                "You do not have permission to execute this command!", 
                ephemeral=True
            )
            return
        
        config = json.load(open("config/config.json", "r"))
        
        if not config["discord"]["logs_channel"] or not config["discord"]["accounts_channel"]:
            await ctx.respond(
                "You must set the logs and Hits channel first with /set channel!",
                ephemeral=True
            )
            return
        
        embed = get_embed()

        await ctx.defer(ephemeral=True)
        await ctx.channel.send(
            embed = discord.Embed(
                title=embed["title"],
                description=embed["description"],
                color=embed["color"],
            ),
            view = LinkAccountView()
        )
        
        await ctx.followup.send("Sent!", ephemeral=True)

def setup(bot: commands.Bot) -> None:
    bot.add_cog(sendEmbed(bot))