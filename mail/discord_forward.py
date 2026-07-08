import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx

from mail.otp_detect import detect_otp

log = logging.getLogger(__name__)

_config = None


def _load_config() -> dict:
    global _config
    if _config is None:
        with open("config/config.json", "r", encoding="utf-8") as f:
            _config = json.load(f)
    return _config


def _truncate(text: str, max_len: int) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


async def _post_webhook(
    webhook_url: str,
    *,
    subject: str,
    body: str,
    from_address: str,
    to_addresses: list[str],
    domain: str,
    otp: dict | None = None,
) -> None:
    fields = [
        {"name": "From", "value": _truncate(from_address or "unknown", 1024), "inline": False},
        {"name": "To", "value": _truncate(", ".join(to_addresses) or "unknown", 1024), "inline": False},
    ]
    if otp and otp.get("code"):
        fields.insert(0, {"name": "Detected OTP", "value": f"`{otp['code']}`", "inline": True})

    embed = {
        "title": _truncate(subject or "(no subject)", 256),
        "description": _truncate((body or "").replace("\r", ""), 4000) or "(empty body)",
        "color": 0xF1C40F if otp else 0x3498DB,
        "fields": fields,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {
            "text": f"{'OTP webhook' if otp else 'Inbox webhook'} • {domain}",
        },
    }

    payload = {
        "username": "OTP Inbox" if otp else "Mail Inbox",
        "embeds": [embed],
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(webhook_url, json=payload)
        response.raise_for_status()


async def _push_otp_to_playtime(
    *,
    recipients: list[str],
    from_address: str,
    subject: str,
    body: str,
    code: str | None,
    bridge_url: str,
    bridge_token: str,
) -> None:
    if not bridge_url or not recipients:
        return

    payload = {
        "to": recipients,
        "from": from_address,
        "subject": subject,
        "text": body,
        "html": body if "<" in body and ">" in body else "",
        "code": code,
    }
    headers = {"X-OTP-Bridge-Token": bridge_token} if bridge_token else {}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(bridge_url, json=payload, headers=headers)
            response.raise_for_status()
        log.info(
            "[otp-bridge] pushed to playtime for %s%s",
            ", ".join(recipients),
            f" code={code}" if code else "",
        )
    except httpx.HTTPError as err:
        log.warning("[otp-bridge] playtime push failed: %s", err)


async def forward_email(
    *,
    from_address: str,
    to_addresses: list[str],
    subject: str,
    body: str,
) -> None:
    cfg = _load_config()
    mail_cfg = cfg.get("mail", {})
    domain = cfg.get("domain", "mail.local")

    webhook_all = mail_cfg.get("discord_webhook_all", "")
    webhook_otp = mail_cfg.get("discord_webhook_otp", "")
    bridge_url = mail_cfg.get("otp_bridge_url", "")
    bridge_token = mail_cfg.get("otp_bridge_token", "")

    if not webhook_all:
        return

    recipients = [addr.lower() for addr in to_addresses if addr]
    otp = detect_otp(subject or "", body or "", from_address or "")

    try:
        await _post_webhook(
            webhook_all,
            subject=subject,
            body=body,
            from_address=from_address,
            to_addresses=recipients,
            domain=domain,
        )
        log.info('[discord] posted to all webhook (%s)', subject or "(no subject)")
    except httpx.HTTPError as err:
        log.warning("[discord] all webhook failed: %s", err)

    if otp.get("is_otp") and webhook_otp:
        try:
            await _post_webhook(
                webhook_otp,
                subject=subject,
                body=body,
                from_address=from_address,
                to_addresses=recipients,
                domain=domain,
                otp=otp,
            )
            log.info('[discord] posted to otp webhook (%s)', subject or "(no subject)")
        except httpx.HTTPError as err:
            log.warning("[discord] otp webhook failed: %s", err)

    if otp.get("is_otp") and bridge_url:
        await _push_otp_to_playtime(
            recipients=recipients,
            from_address=from_address,
            subject=subject or "",
            body=body or "",
            code=otp.get("code"),
            bridge_url=bridge_url,
            bridge_token=bridge_token,
        )


def schedule_forward(**kwargs) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(forward_email(**kwargs))
    except RuntimeError:
        asyncio.run(forward_email(**kwargs))
