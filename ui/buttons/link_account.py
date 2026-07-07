from ui.modals.modal_one import MyModalOne
import discord
import json

styles = {
    "primary":   discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success":   discord.ButtonStyle.success,
    "danger":    discord.ButtonStyle.danger,
}

def bconfig():
    with open("config/bot.json") as f:
        config = json.load(f)["verification_button"]

    return {
        "text": config["text"], 
        "color": config["color"]
    }

class LinkAccountButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            custom_id="persistent:button_one"
        )

        config = bconfig()
        self.label = config["text"]
        self.style = styles[config["color"]]

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(MyModalOne())

class LinkAccountView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(LinkAccountButton())