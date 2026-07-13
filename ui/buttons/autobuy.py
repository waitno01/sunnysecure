import json

import discord

from database.database import DBConnection
from ui.modals.autobuy import LinkLtcModal, SellMfaModal, WithdrawModal


def _autobuy_cfg() -> dict:
    with open("config/config.json", "r") as f:
        return json.load(f).get("autobuy") or {}


class LinkLtcButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Link LTC",
            style=discord.ButtonStyle.primary,
            custom_id="persistent:autobuy_link_ltc",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LinkLtcModal())


class WithdrawButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Withdraw",
            style=discord.ButtonStyle.secondary,
            custom_id="persistent:autobuy_withdraw",
        )

    async def callback(self, interaction: discord.Interaction):
        with DBConnection() as db:
            bals = db.autobuy_balances(interaction.user.id)
            ltc = db.autobuy_get_ltc(interaction.user.id)

        if not ltc:
            await interaction.response.send_message(
                "Link an LTC address first using **Link LTC**.",
                ephemeral=True,
            )
            return

        if bals["available_usd"] <= 0:
            await interaction.response.send_message(
                f"No withdrawable balance yet.\n"
                f"Available: **${bals['available_usd']:.2f}** · "
                f"Pending (24h): **${bals['pending_usd']:.2f}**",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(WithdrawModal(bals["available_usd"]))


class SellMfaButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Sell MFA",
            style=discord.ButtonStyle.success,
            custom_id="persistent:autobuy_sell_mfa",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SellMfaModal())


class AutobuyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(LinkLtcButton())
        self.add_item(WithdrawButton())
        self.add_item(SellMfaButton())


def build_autobuy_embed() -> discord.Embed:
    cfg = _autobuy_cfg()
    emb = cfg.get("embed") or {}
    price = float(cfg.get("price_per_mfa") or 5.0)
    max_day = int(cfg.get("max_accounts_per_day") or 10)
    max_submit = int(cfg.get("max_accounts_per_submit") or 10)

    description = (emb.get("description") or "").format(
        price=price,
        max_day=max_day,
        max_submit=max_submit,
    )

    embed = discord.Embed(
        title=emb.get("title") or "Account Selling Service",
        description=description,
        color=int(emb.get("color") or 0x2B2D31),
    )
    embed.set_footer(text=emb.get("footer") or "Automated account selling service")
    return embed
