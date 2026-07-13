"""Litecoin hot wallet helpers for autobuy payouts."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path

import httpx

logger = logging.getLogger("bot")

CONFIG_PATH = Path("config/config.json")
WALLET_DB = Path("database/ltc_wallet.db")
WALLET_NAME = "autobuy_hot"

# Legacy P2PKH (L...), P2SH (M...), bech32 (ltc1...)
LTC_ADDRESS_RE = re.compile(
    r"^(?:[LM][a-km-zA-HJ-NP-Z1-9]{25,34}|ltc1[a-z0-9]{39,59})$"
)

_lock = threading.Lock()
_wallet_singleton: "LtcWallet | None" = None


def is_valid_ltc_address(address: str) -> bool:
    address = (address or "").strip()
    return bool(LTC_ADDRESS_RE.match(address))


def _load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def _save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def get_ltc_usd_rate() -> float:
    """USD per 1 LTC. Prefers config override, else CoinGecko."""
    config = _load_config()
    autobuy = config.get("autobuy") or {}
    fixed = autobuy.get("ltc_usd_rate")
    if fixed is not None:
        try:
            rate = float(fixed)
            if rate > 0:
                return rate
        except (TypeError, ValueError):
            pass

    try:
        resp = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "litecoin", "vs_currencies": "usd"},
            timeout=15.0,
        )
        resp.raise_for_status()
        rate = float(resp.json()["litecoin"]["usd"])
        if rate <= 0:
            raise ValueError("invalid LTC rate")
        return rate
    except Exception:
        logger.exception("Failed to fetch LTC/USD rate")
        raise RuntimeError("Could not fetch LTC/USD price. Try again shortly.")


class LtcWallet:
    def __init__(self, wif: str, address: str):
        self.wif = wif
        self.address = address

    @classmethod
    def ensure_configured(cls) -> "LtcWallet":
        from bitcoinlib.keys import Key
        from bitcoinlib.wallets import Wallet, wallets_list

        config = _load_config()
        autobuy = config.setdefault("autobuy", {})
        wallet_cfg = autobuy.setdefault("ltc_wallet", {})

        wif = (wallet_cfg.get("wif") or "").strip()
        address = (wallet_cfg.get("address") or "").strip()

        if not wif or not address:
            key = Key(network="litecoin")
            wif = key.wif()
            # Prefer legacy L... deposit address for broader exchange support
            address = Key(import_key=wif, network="litecoin").address()
            wallet_cfg["wif"] = wif
            wallet_cfg["address"] = address
            wallet_cfg["network"] = "litecoin"
            _save_config(config)
            logger.info("Generated new Litecoin hot wallet: %s", address)

        WALLET_DB.parent.mkdir(parents=True, exist_ok=True)
        db_uri = str(WALLET_DB.resolve())

        existing = {w["name"] for w in wallets_list(db_uri)}
        if WALLET_NAME not in existing:
            Wallet.create(
                WALLET_NAME,
                keys=wif,
                network="litecoin",
                db_uri=db_uri,
                encoding="base58",
            )
            logger.info("Created bitcoinlib wallet DB for %s", address)

        # Keep config address in sync with wallet key when possible
        try:
            w = Wallet(WALLET_NAME, db_uri=db_uri)
            derived = w.get_key().address
            if derived and derived != address:
                wallet_cfg["address"] = derived
                address = derived
                _save_config(config)
        except Exception:
            logger.exception("Could not sync LTC wallet address from DB")

        return cls(wif=wif, address=address)

    def _open(self):
        from bitcoinlib.wallets import Wallet

        return Wallet(WALLET_NAME, db_uri=str(WALLET_DB.resolve()))

    def balance_ltc(self) -> float:
        w = self._open()
        try:
            w.utxos_update()
        except Exception:
            logger.exception("LTC utxos_update failed")
        # bitcoinlib balance is in smallest units / sat depending on version — use balance() float helper
        try:
            bal = w.balance(as_string=False)
            # balance often returned in satoshi-like units for LTC (litoshi = 1e-8)
            if isinstance(bal, (int, float)) and bal > 1000:
                return float(bal) / 1e8
            return float(bal or 0)
        except Exception:
            logger.exception("LTC balance read failed")
            return 0.0

    def send_ltc(self, to_address: str, amount_ltc: float) -> str:
        """Broadcast an LTC payment. Returns txid."""
        if not is_valid_ltc_address(to_address):
            raise ValueError("Invalid Litecoin address")
        if amount_ltc <= 0:
            raise ValueError("Amount must be positive")

        w = self._open()
        try:
            w.utxos_update()
        except Exception:
            logger.exception("LTC utxos_update before send failed")

        # bitcoinlib send_to expects amount in BTC/LTC units when offline=False
        tx = w.send_to(
            to_address,
            amount_ltc,
            fee="normal",
            offline=False,
        )
        txid = getattr(tx, "txid", None) or getattr(tx, "hash", None)
        if not txid and isinstance(tx, dict):
            txid = tx.get("txid") or tx.get("hash")
        if not txid:
            raise RuntimeError("LTC send completed but no txid was returned")
        return str(txid)


def get_ltc_wallet() -> LtcWallet:
    global _wallet_singleton
    with _lock:
        if _wallet_singleton is None:
            _wallet_singleton = LtcWallet.ensure_configured()
        return _wallet_singleton
