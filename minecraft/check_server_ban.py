"""Minecraft server ban checks (Hypixel / DonutSMP) via Mineflayer + ColdProxy."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("bot")

CHECK_JS = Path(__file__).resolve().parent / "ban_check" / "check.js"
NODE = os.environ.get("NODE_BIN", "node")

SERVERS = {
    "hypixel": {"host": "mc.hypixel.net", "port": 25565, "label": "Hypixel"},
    "donutsmp": {"host": "donutsmp.net", "port": 25565, "label": "DonutSMP"},
}


def _load_cfg() -> dict:
    with open("config/config.json", "r") as f:
        return json.load(f)


def _reject_toggles(cfg: dict | None = None) -> dict:
    cfg = cfg or _load_cfg()
    autosecure = cfg.get("autosecure") or {}
    reject = autosecure.get("reject") or {}
    return {
        "check_hypixel_ban": bool(reject.get("check_hypixel_ban", False)),
        "check_donutsmp_ban": bool(reject.get("check_donutsmp_ban", False)),
    }


def _coldproxy_line(cfg: dict | None = None) -> str | None:
    cfg = cfg or _load_cfg()
    cp = cfg.get("coldproxy") or {}
    host = (cp.get("host") or "").strip()
    user_tmpl = (cp.get("user") or "").strip()
    password = cp.get("pass") or cp.get("password") or ""
    if not host or not user_tmpl or not password:
        return None
    port_min = int(cp.get("port_min") or 30000)
    port_max = int(cp.get("port_max") or 34999)
    ssid = random.randint(min(port_min, port_max), max(port_min, port_max))
    user = user_tmpl.replace("{ssid}", str(ssid))
    # ColdProxy uses gateway port == session id
    return f"{host}:{ssid}:{user}:{password}"


async def _profile_from_ssid(ssid: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://api.minecraftservices.com/minecraft/profile",
                headers={"Authorization": f"Bearer {ssid}"},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get("name") and data.get("id"):
                return {"name": data["name"], "uuid": data["id"]}
    except Exception:
        logger.exception("Failed to fetch MC profile for ban check")
    return None


def _run_check_sync(
    *,
    host: str,
    port: int,
    token: str,
    name: str | None,
    uuid: str | None,
    proxy: str | None,
    attempts: int = 3,
    timeout_ms: int = 45000,
) -> dict:
    if not CHECK_JS.is_file():
        return {"status": "error", "reason": f"ban check script missing: {CHECK_JS}"}

    cmd = [
        NODE,
        str(CHECK_JS),
        "--host",
        host,
        "--port",
        str(port),
        "--token",
        token,
        "--attempts",
        str(attempts),
        "--timeout",
        str(timeout_ms),
    ]
    if name:
        cmd.extend(["--name", name])
    if uuid:
        cmd.extend(["--uuid", uuid])
    if proxy:
        cmd.extend(["--proxy", proxy])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=(timeout_ms / 1000.0) * attempts + 30,
            cwd=str(CHECK_JS.parent),
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "ban check subprocess timed out"}
    except Exception as exc:
        return {"status": "error", "reason": f"ban check failed to start: {exc}"}

    out = (proc.stdout or "").strip().splitlines()
    raw = out[-1] if out else (proc.stderr or "").strip()
    if not raw:
        return {
            "status": "error",
            "reason": f"ban check empty output (exit={proc.returncode})",
        }
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "error", "reason": f"ban check bad JSON: {raw[:300]}"}


async def check_server_ban(
    server_key: str,
    ssid: str,
    *,
    name: str | None = None,
    uuid: str | None = None,
) -> dict:
    meta = SERVERS.get(server_key)
    if not meta:
        return {"status": "error", "reason": f"unknown server {server_key}"}

    cfg = _load_cfg()
    proxy = _coldproxy_line(cfg)
    if not proxy:
        logger.warning("coldproxy not configured — ban check for %s without proxy", server_key)

    if not name or not uuid:
        profile = await _profile_from_ssid(ssid)
        if profile:
            name = name or profile["name"]
            uuid = uuid or profile["uuid"]

    result = await asyncio.to_thread(
        _run_check_sync,
        host=meta["host"],
        port=int(meta["port"]),
        token=ssid,
        name=name,
        uuid=uuid,
        proxy=proxy,
        attempts=3,
        timeout_ms=45000,
    )
    result["server"] = server_key
    result["label"] = meta["label"]
    return result


def _ssid_from_account(account: dict) -> str | None:
    mc = (account or {}).get("minecraft") or {}
    ssid = mc.get("SSID") or mc.get("ssid")
    if not ssid or ssid is False or str(ssid).lower() in ("false", "none", ""):
        return None
    return str(ssid)


async def apply_ban_checks(account: dict) -> str | None:
    """Run enabled Hypixel/DonutSMP ban checks. Return reject reason or None."""
    toggles = _reject_toggles()
    wanted = []
    if toggles["check_hypixel_ban"]:
        wanted.append("hypixel")
    if toggles["check_donutsmp_ban"]:
        wanted.append("donutsmp")
    if not wanted:
        return None

    ssid = _ssid_from_account(account)
    if not ssid:
        # No Java SSID — cannot check; do not reject (may be Bedrock-only / no MC)
        logger.info("ban checks skipped — no Minecraft SSID on account")
        return None

    mc = account.get("minecraft") or {}
    name = mc.get("name")
    if name and (
        "no minecraft" in str(name).lower()
        or "failed" in str(name).lower()
        or "no java" in str(name).lower()
    ):
        name = None

    for key in wanted:
        label = SERVERS[key]["label"]
        print(f"[~] - Checking {label} ban status...")
        result = await check_server_ban(key, ssid, name=name)
        status = result.get("status")
        reason = result.get("reason") or "unknown"
        ban_id = result.get("ban_id")
        logger.info(
            "ban check %s status=%s attempts=%s reason=%s",
            key,
            status,
            result.get("attempts"),
            reason[:200] if isinstance(reason, str) else reason,
        )
        if status == "ok":
            print(f"[+] - {label}: not banned")
            continue
        if status == "banned":
            detail = reason
            if ban_id:
                detail = f"{reason} (Ban ID #{ban_id})"
            # Infrastructure / script failures must not reject the account
            soft = str(reason or "").lower()
            if any(
                x in soft
                for x in (
                    "syntaxerror",
                    "bad json",
                    "script missing",
                    "failed to start",
                    "subprocess timed out",
                    "empty output",
                    "missing --host",
                    "no java profile",
                    "socketclosed",
                    "transient",
                    "assumed banned",
                )
            ) and not re.search(r"\bbanned\b|ban\s*id|#\w+", soft):
                logger.error(
                    "ban check %s infrastructure failure — NOT rejecting: %s",
                    key,
                    reason,
                )
                print(f"[!] - {label}: check failed (infra) — skipping reject: {reason[:120]}")
                continue
            return f"{label} ban detected: {detail}"
        # Unexpected error after retries — only assume banned for join/kick text,
        # not for checker tooling failures.
        soft = str(reason or "").lower()
        if any(
            x in soft
            for x in (
                "syntaxerror",
                "bad json",
                "script missing",
                "failed to start",
                "subprocess timed out",
                "empty output",
                "proxy connect failed",
                "coldproxy",
                "socketclosed",
                "transient",
            )
        ):
            logger.error(
                "ban check %s soft error — NOT rejecting: %s",
                key,
                reason,
            )
            print(f"[!] - {label}: check error — skipping reject: {reason[:120]}")
            continue
        return f"{label} join failed after retries (assumed banned): {reason}"

    return None
