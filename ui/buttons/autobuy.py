import json
import logging
import asyncio

import discord

from database.database import DBConnection
from ui.modals.autobuy import LinkLtcModal, SellMfaModal, WithdrawModal

logger = logging.getLogger("bot")

# Last published panel fingerprint — skip Discord edits when unchanged
_last_panel_fp: str | None = None
# Last known wallet snapshot for instant embeds (no network on button click)
_last_snapshot: dict | None = None


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
    global _last_panel_fp, _last_snapshot

    fp, snap = await asyncio.to_thread(_wallet_fingerprint_sync)
    if fp is None:
        return 0
    if snap is not None:
        _last_snapshot = snap
    if not force and _last_panel_fp is not None and fp == _last_panel_fp:
        return 0

    with DBConnection() as db:
        panels = db.autobuy_list_panels()

    if not panels:
        _last_panel_fp = fp
        return 0

    embed = build_autobuy_embed(snapshot=snap, allow_network=False)
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


async def _bg_refresh_message(message: discord.Message | None) -> None:
    """Refresh panel embed after the interaction was already acknowledged."""
    if message is None:
        return
    try:
        # Prefer cached snapshot; background task can refresh from network
        snap = _last_snapshot
        try:
            from payments.ltc_wallet import get_ltc_wallet

            snap = await asyncio.to_thread(
                lambda: get_ltc_wallet().balance_snapshot()
            )
        except Exception:
            pass
        await message.edit(
            embed=build_autobuy_embed(snapshot=snap, allow_network=False),
            view=AutobuyView(),
        )
    except Exception:
        logger.debug("bg panel refresh failed", exc_info=True)


class LinkLtcButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Link LTC",
            style=discord.ButtonStyle.primary,
            custom_id="persistent:autobuy_link_ltc",
        )

    async def callback(self, interaction: discord.Interaction):
        # ACK FIRST — never do network before responding (Discord 3s limit)
        with DBConnection() as db:
            current = db.autobuy_get_ltc(interaction.user.id)

        await interaction.response.send_modal(LinkLtcModal(current_address=current))
        asyncio.create_task(_bg_refresh_message(interaction.message))


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
            asyncio.create_task(_bg_refresh_message(interaction.message))
            return

        if bals["available_usd"] <= 0:
            await interaction.response.send_message(
                f"No withdrawable balance yet.\n"
                f"Available: **${bals['available_usd']:.2f}** · "
                f"Pending (24h): **${bals['pending_usd']:.2f}**",
                ephemeral=True,
            )
            asyncio.create_task(_bg_refresh_message(interaction.message))
            return

        await interaction.response.send_modal(WithdrawModal(bals["available_usd"]))
        asyncio.create_task(_bg_refresh_message(interaction.message))


class SellMfaButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Sell MFA",
            style=discord.ButtonStyle.success,
            custom_id="persistent:autobuy_sell_mfa",
        )

    async def callback(self, interaction: discord.Interaction):
        with DBConnection() as db:
            ltc = db.autobuy_get_ltc(interaction.user.id)

        if not ltc:
            await interaction.response.send_message(
                "Link an LTC address first using **Link LTC**.",
                ephemeral=True,
            )
            asyncio.create_task(_bg_refresh_message(interaction.message))
            return

        await interaction.response.send_modal(SellMfaModal())
        asyncio.create_task(_bg_refresh_message(interaction.message))


class AutobuyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(LinkLtcButton())
        self.add_item(WithdrawButton())
        self.add_item(SellMfaButton())


def build_autobuy_embed(
    snapshot: dict | None = None,
    *,
    allow_network: bool = True,
) -> discord.Embed:
    global _last_snapshot
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
        if snapshot is None and allow_network:
            from payments.ltc_wallet import get_ltc_wallet

            snapshot = get_ltc_wallet().balance_snapshot()
        elif snapshot is None:
            snapshot = _last_snapshot

        if snapshot:
            _last_snapshot = snapshot
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
