import json
import logging
import asyncio

import discord

from database.database import DBConnection
from ui.modals.autobuy import LinkLtcModal, SellMfaModal, WithdrawModal

logger = logging.getLogger("bot")

# Last published panel fingerprint — skip Discord edits when unchanged
_last_panel_fp: str | None = None


def _autobuy_cfg() -> dict:
    with open("config/config.json", "r") as f:
        return json.load(f).get("autobuy") or {}


def _wallet_fingerprint() -> tuple[str | None, dict | None]:
    """Return (fingerprint, snapshot) for change detection."""
    try:
        from payments.ltc_wallet import get_ltc_wallet

        snap = get_ltc_wallet().balance_snapshot()
        fp = f"{snap['litoshis']}:{snap['usd']:.2f}"
        return fp, snap
    except Exception:
        logger.exception("wallet fingerprint failed")
        return None, None


async def refresh_autobuy_panels(bot: discord.Client, *, force: bool = False) -> int:
    """Rebuild embeds on all tracked panels when LTC balance changes.

    Uses explorer balance so deposits appear without button interaction.
    Returns number of messages successfully edited.
    """
    global _last_panel_fp

    fp, snap = await asyncio.to_thread(_wallet_fingerprint_sync)
    if fp is None:
        return 0
    if not force and _last_panel_fp is not None and fp == _last_panel_fp:
        return 0

    with DBConnection() as db:
        panels = db.autobuy_list_panels()

    if not panels:
        _last_panel_fp = fp
        return 0

    embed = build_autobuy_embed(snapshot=snap)
    view = AutobuyView()
    edited = 0

    for panel in panels:
        try:
            channel = bot.get_channel(panel["channel_id"])
            if channel is None:
                channel = await bot.fetch_channel(panel["channel_id"])
            msg = await channel.fetch_message(panel["message_id"])
            await msg.edit(embed=embed, view=view)
            edited += 1
        except discord.NotFound:
            with DBConnection() as db:
                db.autobuy_remove_panel(panel["message_id"])
            logger.info("Removed missing autobuy panel %s", panel["message_id"])
        except Exception:
            logger.exception(
                "Failed to refresh autobuy panel %s in channel %s",
                panel["message_id"],
                panel["channel_id"],
            )

    _last_panel_fp = fp
    if edited:
        logger.info(
            "Refreshed %s autobuy panel(s) (ltc=%s usd=$%.2f source=%s)",
            edited,
            snap.get("ltc") if snap else "?",
            float(snap.get("usd") or 0) if snap else 0,
            snap.get("source") if snap else "?",
        )
    return edited


def _wallet_fingerprint_sync() -> tuple[str | None, dict | None]:
    return _wallet_fingerprint()


class LinkLtcButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Link LTC",
            style=discord.ButtonStyle.primary,
            custom_id="persistent:autobuy_link_ltc",
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            if interaction.message:
                await interaction.message.edit(embed=build_autobuy_embed(), view=AutobuyView())
        except Exception:
            pass
        await interaction.response.send_modal(LinkLtcModal())


class WithdrawButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Withdraw",
            style=discord.ButtonStyle.secondary,
            custom_id="persistent:autobuy_withdraw",
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            if interaction.message:
                await interaction.message.edit(embed=build_autobuy_embed(), view=AutobuyView())
        except Exception:
            pass

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
        try:
            if interaction.message:
                await interaction.message.edit(embed=build_autobuy_embed(), view=AutobuyView())
        except Exception:
            pass

        with DBConnection() as db:
            ltc = db.autobuy_get_ltc(interaction.user.id)

        if not ltc:
            await interaction.response.send_message(
                "Link an LTC address first using **Link LTC**.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(SellMfaModal())


class AutobuyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(LinkLtcButton())
        self.add_item(WithdrawButton())
        self.add_item(SellMfaButton())


def build_autobuy_embed(snapshot: dict | None = None) -> discord.Embed:
    cfg = _autobuy_cfg()
    emb = cfg.get("embed") or {}
    price = float(cfg.get("price_per_mfa") or 5.0)
    max_day = int(cfg.get("max_accounts_per_day") or 10)
    max_submit = int(cfg.get("max_accounts_per_submit") or 10)
    pending = int(cfg.get("pending_hours") or 24)
    check_h = float(cfg.get("hold_check_interval_hours") or 6)

    description = (emb.get("description") or "").format(
        price=price,
        max_day=max_day,
        max_submit=max_submit,
        pending=pending,
        check_hours=check_h,
    )

    ltc_usd_line = "LTC Balance: unavailable"
    try:
        if snapshot is None:
            from payments.ltc_wallet import get_ltc_wallet

            snapshot = get_ltc_wallet().balance_snapshot()
        usd = float(snapshot.get("usd") or 0)
        ltc = float(snapshot.get("ltc") or 0)
        ltc_usd_line = f"LTC Balance: **${usd:.2f}** ({ltc:.8f} LTC)"
    except Exception:
        logger.exception("build_autobuy_embed balance failed")

    description = f"{description}\n{ltc_usd_line}"

    embed = discord.Embed(
        title=emb.get("title") or "Account Selling Service",
        description=description,
        color=int(emb.get("color") or 0x2B2D31),
    )
    embed.set_footer(text=emb.get("footer") or "Automated account selling service")
    return embed
