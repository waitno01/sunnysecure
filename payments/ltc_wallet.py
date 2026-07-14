"""Litecoin hot wallet helpers for autobuy payouts."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
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
_balance_cache: dict = {"ltc": None, "at": 0.0, "source": None}
_BALANCE_CACHE_TTL = 8.0  # seconds — avoid hammering explorers / bitcoinlib

# Dust / fee defaults (litoshis)
_DUST = 546
_FEE_PER_BYTE = 50  # litoshis/vbyte — LTC is cheap; keep simple
_MIN_FEE = 10_000
_MAX_FEE = 200_000


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


_rate_cache: dict = {"rate": None, "at": 0.0}
_RATE_CACHE_TTL = 300.0  # 5 minutes


def get_ltc_usd_rate() -> float:
    """USD per 1 LTC. Prefers config override, else CoinGecko (cached)."""
    global _rate_cache
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

    now = time.monotonic()
    if _rate_cache["rate"] is not None and now - float(_rate_cache["at"] or 0) < _RATE_CACHE_TTL:
        return float(_rate_cache["rate"])

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
        _rate_cache = {"rate": rate, "at": now}
        return rate
    except Exception:
        logger.exception("Failed to fetch LTC/USD rate")
        if _rate_cache["rate"] is not None:
            logger.warning("Using stale LTC/USD rate cache: %s", _rate_cache["rate"])
            return float(_rate_cache["rate"])
        # Last-resort hard fallback so withdraws aren't blocked by CoinGecko 429
        return 43.5


def fetch_address_balance_ltc(address: str) -> float | None:
    """Read confirmed+unconfirmed balance from public explorers (detects deposits fast)."""
    address = (address or "").strip()
    if not address:
        return None

    # BlockCypher — final_balance includes unconfirmed
    try:
        resp = httpx.get(
            f"https://api.blockcypher.com/v1/ltc/main/addrs/{address}/balance",
            timeout=12.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            bal = int(data.get("final_balance") or data.get("balance") or 0)
            return bal / 1e8
    except Exception:
        logger.debug("BlockCypher LTC balance failed", exc_info=True)

    # Fallback: Blockchair
    try:
        resp = httpx.get(
            f"https://api.blockchair.com/litecoin/dashboards/address/{address}",
            timeout=12.0,
        )
        if resp.status_code == 200:
            data = resp.json().get("data") or {}
            entry = data.get(address) or next(iter(data.values()), None)
            if entry:
                addr = entry.get("address") or {}
                bal = int(addr.get("balance") or 0)
                return bal / 1e8
    except Exception:
        logger.debug("Blockchair LTC balance failed", exc_info=True)

    return None


def fetch_address_utxos(address: str) -> list[dict]:
    """Return unspent outputs: {txid, output_n, value, script, confirmations}."""
    address = (address or "").strip()
    if not address:
        return []

    # BlockCypher
    try:
        resp = httpx.get(
            f"https://api.blockcypher.com/v1/ltc/main/addrs/{address}",
            params={"unspentOnly": "true", "includeScript": "true"},
            timeout=20.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            out: list[dict] = []
            for ref in data.get("txrefs") or []:
                if ref.get("spent"):
                    continue
                out.append(
                    {
                        "txid": ref["tx_hash"],
                        "output_n": int(ref["tx_output_n"]),
                        "value": int(ref["value"]),
                        "script": ref.get("script") or "",
                        "confirmations": int(ref.get("confirmations") or 0),
                    }
                )
            for ref in data.get("unconfirmed_txrefs") or []:
                if ref.get("spent"):
                    continue
                out.append(
                    {
                        "txid": ref["tx_hash"],
                        "output_n": int(ref["tx_output_n"]),
                        "value": int(ref["value"]),
                        "script": ref.get("script") or "",
                        "confirmations": 0,
                    }
                )
            if out:
                return out
    except Exception:
        logger.exception("BlockCypher UTXO fetch failed for %s", address)

    # Blockchair fallback
    try:
        resp = httpx.get(
            f"https://api.blockchair.com/litecoin/dashboards/address/{address}",
            params={"limit": "50"},
            timeout=20.0,
        )
        if resp.status_code == 200:
            data = resp.json().get("data") or {}
            entry = data.get(address) or next(iter(data.values()), None)
            utxos = (entry or {}).get("utxo") or []
            out = []
            for u in utxos:
                out.append(
                    {
                        "txid": u.get("transaction_hash") or u.get("txid"),
                        "output_n": int(u.get("index") if u.get("index") is not None else u.get("tx_output_n") or 0),
                        "value": int(u.get("value") or 0),
                        "script": "",
                        "confirmations": int(u.get("block_id") or 0) and 1 or 0,
                    }
                )
            return [x for x in out if x.get("txid") and x["value"] > 0]
    except Exception:
        logger.exception("Blockchair UTXO fetch failed for %s", address)

    return []


def broadcast_ltc_raw(raw_hex: str) -> str:
    """Broadcast a signed raw tx. Returns network txid. Raises on total failure."""
    raw_hex = raw_hex.strip().lower()
    if raw_hex.startswith("0x"):
        raw_hex = raw_hex[2:]
    errors: list[str] = []

    # 1) BlockCypher
    try:
        resp = httpx.post(
            "https://api.blockcypher.com/v1/ltc/main/txs/push",
            json={"tx": raw_hex},
            timeout=45.0,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            tx = data.get("tx") or data
            txid = tx.get("hash") or data.get("hash")
            if txid:
                return str(txid)
            errors.append(f"blockcypher: no hash in {resp.text[:200]}")
        else:
            errors.append(f"blockcypher HTTP {resp.status_code}: {resp.text[:300]}")
    except Exception as exc:
        errors.append(f"blockcypher: {exc}")

    # 2) Blockchair
    try:
        resp = httpx.post(
            "https://api.blockchair.com/litecoin/push/transaction",
            data={"data": raw_hex},
            timeout=45.0,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            txid = (data.get("data") or {}).get("transaction_hash") or data.get("transaction_hash")
            if txid:
                return str(txid)
            errors.append(f"blockchair: no hash in {resp.text[:200]}")
        else:
            errors.append(f"blockchair HTTP {resp.status_code}: {resp.text[:300]}")
    except Exception as exc:
        errors.append(f"blockchair: {exc}")

    # 3) litecoinspace / mempool-style (if available)
    for url in (
        "https://litecoinspace.org/api/tx",
        "https://lte.bitaps.com/send/raw/transaction",
    ):
        try:
            resp = httpx.post(url, content=raw_hex, headers={"Content-Type": "text/plain"}, timeout=45.0)
            if resp.status_code in (200, 201):
                text = (resp.text or "").strip().strip('"')
                if re.fullmatch(r"[0-9a-fA-F]{64}", text):
                    return text
                try:
                    j = resp.json()
                    txid = j.get("txid") or j.get("hash") or j.get("result")
                    if txid and re.fullmatch(r"[0-9a-fA-F]{64}", str(txid)):
                        return str(txid)
                except Exception:
                    pass
            errors.append(f"{url}: HTTP {resp.status_code} {resp.text[:200]}")
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError("Broadcast failed: " + " | ".join(errors[:6]))


class LtcWallet:
    def __init__(self, wif: str, address: str):
        self.wif = wif
        self.address = address
        self._bal_lock = threading.Lock()

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

        try:
            w = Wallet(WALLET_NAME, db_uri=db_uri)
            funded = None
            try:
                for u in w.utxos() or []:
                    if u.get("address") and int(u.get("value") or 0) > 0:
                        funded = u["address"]
                        break
            except Exception:
                pass
            if funded and address and funded != address:
                logger.warning(
                    "Configured LTC address %s differs from funded UTXO address %s — keeping configured for deposits display; UTXOs remain spendable",
                    address,
                    funded,
                )
            if not address and funded:
                wallet_cfg["address"] = funded
                address = funded
                _save_config(config)
        except Exception:
            logger.exception("Could not inspect LTC wallet addresses from DB")

        return cls(wif=wif, address=address)

    def _open(self):
        from bitcoinlib.wallets import Wallet

        return Wallet(WALLET_NAME, db_uri=str(WALLET_DB.resolve()))

    def _legacy_key_for_address(self, address: str):
        """Return HDKey (legacy/P2PKH) that produces ``address``."""
        from bitcoinlib.keys import HDKey

        w = self._open()
        for wk in w.keys():
            addr = getattr(wk, "address", None)
            if addr != address:
                continue
            try:
                priv_hex = wk.key().private_hex
                key = HDKey(priv_hex, network="litecoin", witness_type="legacy")
                if key.address() == address:
                    return key
            except Exception:
                logger.exception("Failed deriving legacy key for %s", address)
        raise RuntimeError(f"No private key in wallet for deposit address {address}")

    def _balance_bitcoinlib(self) -> float:
        with self._bal_lock:
            w = self._open()
            try:
                w.utxos_update()
            except Exception:
                logger.exception("LTC utxos_update failed")
            try:
                bal = w.balance(as_string=False)
                return float(bal or 0) / 1e8
            except Exception:
                logger.exception("LTC balance read failed")
                return 0.0

    def balance_ltc(self, *, prefer_explorer: bool = True, use_cache: bool = True) -> float:
        """Hot-wallet LTC balance. Prefers explorer so deposits show up without button clicks."""
        global _balance_cache
        now = time.monotonic()
        if use_cache and _balance_cache["ltc"] is not None:
            if now - float(_balance_cache["at"] or 0) < _BALANCE_CACHE_TTL:
                return float(_balance_cache["ltc"])

        ltc: float | None = None
        source = "bitcoinlib"

        if prefer_explorer:
            ltc = fetch_address_balance_ltc(self.address)
            if ltc is not None:
                source = "explorer"

        if ltc is None:
            ltc = self._balance_bitcoinlib()
            source = "bitcoinlib"

        _balance_cache = {"ltc": float(ltc), "at": now, "source": source}
        return float(ltc)

    def balance_usd(self) -> float:
        """Hot-wallet balance converted to USD at current LTC rate."""
        ltc = self.balance_ltc()
        if ltc <= 0:
            return 0.0
        return ltc * get_ltc_usd_rate()

    def balance_snapshot(self) -> dict:
        """Single consistent read for panel/embeds: ltc, usd, rate, litoshis."""
        ltc = self.balance_ltc(prefer_explorer=True, use_cache=False)
        try:
            rate = get_ltc_usd_rate()
        except Exception:
            rate = 0.0
        usd = ltc * rate if rate > 0 else 0.0
        return {
            "ltc": ltc,
            "usd": usd,
            "rate": rate,
            "litoshis": int(round(ltc * 1e8)),
            "address": self.address,
            "source": _balance_cache.get("source"),
        }

    def send_ltc(self, to_address: str, amount_ltc: float) -> str:
        """Build, sign (legacy P2PKH), and broadcast an LTC payment. Returns txid.

        Bypasses bitcoinlib service providers (often down) by fetching UTXOs and
        broadcasting via BlockCypher / Blockchair HTTP APIs.
        """
        from bitcoinlib.transactions import Transaction

        if not is_valid_ltc_address(to_address):
            raise ValueError("Invalid Litecoin address")
        if amount_ltc <= 0:
            raise ValueError("Amount must be positive")

        amount_litoshi = int(round(float(amount_ltc) * 1e8))
        if amount_litoshi < 1:
            raise ValueError("Amount too small after conversion to litoshis")

        with self._bal_lock:
            # Prefer live explorer UTXOs — do not depend on bitcoinlib providers
            utxos = fetch_address_utxos(self.address)
            if not utxos:
                # Last resort: local wallet cache
                try:
                    w = self._open()
                    try:
                        w.transactions_remove_unconfirmed()
                    except Exception:
                        pass
                    for u in w.utxos() or []:
                        if (u.get("address") or self.address) != self.address:
                            continue
                        utxos.append(
                            {
                                "txid": u["txid"],
                                "output_n": int(u["output_n"]),
                                "value": int(u["value"]),
                                "script": u.get("script") or "",
                                "confirmations": int(u.get("confirmations") or 0),
                            }
                        )
                except Exception:
                    logger.exception("Local UTXO fallback failed")

            if not utxos:
                raise RuntimeError(
                    f"No spendable UTXOs found for {self.address}. "
                    "Deposit may still be unconfirmed or explorers are unreachable."
                )

            # Largest-first coin select
            utxos = sorted(utxos, key=lambda u: int(u["value"]), reverse=True)
            selected: list[dict] = []
            total_in = 0
            # estimate fee for 1-in 2-out, grow if more inputs needed
            for u in utxos:
                selected.append(u)
                total_in += int(u["value"])
                n_in = len(selected)
                # ~148 vB per p2pkh input, ~34 per output, ~10 overhead
                est_size = 10 + 148 * n_in + 34 * 2
                fee = max(_MIN_FEE, min(_MAX_FEE, est_size * _FEE_PER_BYTE))
                if total_in >= amount_litoshi + fee:
                    break
            else:
                fee = max(_MIN_FEE, min(_MAX_FEE, (10 + 148 * len(selected) + 34 * 2) * _FEE_PER_BYTE))
                raise RuntimeError(
                    f"Insufficient hot-wallet funds: need {amount_litoshi + fee} litoshis "
                    f"(send+fee), have {total_in}"
                )

            n_in = len(selected)
            est_size = 10 + 148 * n_in + 34 * 2
            fee = max(_MIN_FEE, min(_MAX_FEE, est_size * _FEE_PER_BYTE))
            change = total_in - amount_litoshi - fee
            # If change is dust, add to fee
            outputs: list[tuple[int, str]] = [(amount_litoshi, to_address)]
            if change >= _DUST:
                outputs.append((change, self.address))
            else:
                fee += max(0, change)
                change = 0

            priv = self._legacy_key_for_address(self.address)

            tx = Transaction(network="litecoin", witness_type="legacy")
            for u in selected:
                tx.add_input(
                    prev_txid=u["txid"],
                    output_n=int(u["output_n"]),
                    keys=priv,
                    value=int(u["value"]),
                    script_type="sig_pubkey",
                )
            for value, addr in outputs:
                tx.add_output(value, addr)

            tx.sign()
            if not tx.verify():
                raise RuntimeError("Signed LTC transaction failed verification")

            raw_hex = tx.raw_hex()
            logger.info(
                "Broadcasting LTC tx amount=%s fee=%s inputs=%s change=%s raw_len=%s",
                amount_litoshi,
                fee,
                n_in,
                change,
                len(raw_hex),
            )
            txid = broadcast_ltc_raw(raw_hex)

            # Best-effort: import into local wallet so cached UTXOs update
            try:
                w = self._open()
                try:
                    w.transaction_import_raw(raw_hex)
                except Exception:
                    # mark spent locally if import fails
                    try:
                        w.transactions_remove_unconfirmed()
                    except Exception:
                        pass
            except Exception:
                logger.exception("Could not import broadcast tx into local wallet DB")

        global _balance_cache
        _balance_cache = {"ltc": None, "at": 0.0, "source": None}
        return str(txid)


def get_ltc_wallet() -> LtcWallet:
    global _wallet_singleton
    with _lock:
        if _wallet_singleton is None:
            _wallet_singleton = LtcWallet.ensure_configured()
        return _wallet_singleton


def blockcypher_tx_url(txid: str) -> str:
    return f"https://live.blockcypher.com/ltc/tx/{txid}/"
