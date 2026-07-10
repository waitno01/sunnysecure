from discord.ext import commands
import requests
import hashlib
import logging
import discord
import asyncio
import json
import sys
import os

from ui.buttons.link_account import LinkAccountView
from database.database import DBConnection
from mail.server import startServer

config = json.load(open("config/config.json", "r"))
settings = json.load(open("config/bot.json", "r"))

class DiscordBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            case_insensitive=True,
            intents=discord.Intents.all(),
            allowed_mentions=discord.AllowedMentions(roles=False, everyone=False, users=True)
        )
        self.logger = logging.getLogger("bot")
        self.admins = list(map(int, config["owners"]))

        self.statuses = {
            "online": discord.Status.online,
            "idle": discord.Status.idle,
            "dnd": discord.Status.dnd,
            "invisible": discord.Status.invisible,
        }
        
        self.activities = {
            "playing": discord.ActivityType.playing,
            "streaming": discord.ActivityType.streaming,
            "listening": discord.ActivityType.listening,
            "watching": discord.ActivityType.watching,
            "competing": discord.ActivityType.competing,
        }

    
    # Builds fake commands
    async def build_command(self, name: str, description: str, response: str):
        async def cog(ctx: discord.ApplicationContext):
            await ctx.response.send_message(response, ephemeral=True)

        cog.__name__ = name
        command = discord.SlashCommand(cog, name=name, description=description)
        self.add_application_command(command)

    def command_signature(self) -> str:
        payloads = []
        for cmd in self.pending_application_commands:
            try:
                payloads.append(cmd.to_dict())
            except Exception:
                payloads.append({"name": getattr(cmd, "name", "?")})
                
        blob = json.dumps(payloads, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    async def on_ready(self):
        self.add_view(LinkAccountView())
        self._startup_guild_sync_done = True

        # Presence from the config
        presence = settings["presence"]

        # Chosen activities
        activity_text =  presence["activity_text"]
        activity_type = self.activities[presence["activity_type"]]
        activity = discord.Activity(type=activity_type, name=activity_text)

        await self.change_presence(
            status=self.statuses[presence["status"]],
            activity=activity,
        )

        guild_ids = [guild.id for guild in self.guilds]
        await self.sync_commands(guild_ids=guild_ids)
        self.logger.info(f"Synced commands to {len(guild_ids)} guild(s)")

    @staticmethod
    def setup_logging() -> None:
        root = logging.getLogger()
        root.setLevel(logging.INFO)

        file_handler = logging.FileHandler("logs/securing.log", mode="a")
        file_handler.setLevel(logging.INFO)
        root.addHandler(file_handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter("%(levelname)s | %(asctime)s | %(name)s | %(message)s"))

        bot_logger = logging.getLogger("bot")
        bot_logger.addHandler(console_handler)
        bot_logger.propagate = False

        for name in ("discord", "discord.http", "discord.gateway", "httpx", "mail.log", "mail.server"):
            logging.getLogger(name).setLevel(logging.WARNING)

    async def load_cogs(self, directory="./cogs") -> None:
        enabled_commands = settings["enabled_commands"]

        for file in os.listdir(directory):
            if file.endswith(".py"):
                cog_name = file[:-3]
                if enabled_commands["real"][cog_name]:
                    self.load_extension(
                        f"{directory[2:].replace('/', '.')}.{cog_name}"
                    )
                    self.logger.info(f"Loaded: {cog_name}")
            elif not (
                file in ["__pycache__", "utils", "buttons", "modals"] or file.endswith(("pyc", "txt"))
            ):
                await self.load_cogs(f"{directory}/{file}")
            
        for command in enabled_commands["fake"].keys():
            print(command)
            await self.build_command(
                name = enabled_commands["fake"][command]["title"],
                description = enabled_commands["fake"][command]["description"],
                response = enabled_commands["fake"][command]["response"]
            )

        with DBConnection() as database:
            database.setup_tables()

asyncio.set_event_loop(asyncio.new_event_loop())
bot = DiscordBot()

async def main():
    async with bot:
        bot.remove_command("help")
        bot.setup_logging()
        startServer()

        await bot.load_cogs()
        await bot.start(config["tokens"]["bot_token"])

asyncio.run(main())