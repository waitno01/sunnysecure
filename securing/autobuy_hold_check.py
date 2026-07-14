"""Periodic hold checks for autobuy credits (lock / pullback detection)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from database.database import DBConnection
from securing.auth.account_status import get_account_lock_reason
from securing.auth.initial_session import get_session
from securing.utils.security.recovery import verify_password_works

logger = logging.getLogger("bot")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(text[:26], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def check_sold_account(email: str, password: str) -> tuple[str, str | None]:
    """Return (ok|bad|unknown, reason).

    ok — login works and no lock signals
    bad — locked or credentials no longer work (pullback)
    unknown — transient / inconclusive; do not void
    """
    lock_reason = await get_account_lock_reason(email)
    if lock_reason:
        return "bad", lock_reason

    session = get_session()
    try:
        pwd_status = await verify_password_works(
            session, email, password, settle_delay=0.5
        )
    finally:
        await session.aclose()

    if pwd_status == "bad":
        return "bad", "Credentials changed / password no longer works (pullback)"
    if pwd_status == "unknown":
        return "unknown", "Password check inconclusive (rate limit or page change)"

    # Re-check lock after login attempt (HTML may surface soft locks)
    lock_reason = await get_account_lock_reason(email)
    if lock_reason:
        return "bad", lock_reason

    return "ok", None


async def process_due_hold_checks(
    *,
    interval_hours: float = 6.0,
    limit: int = 20,
) -> dict:
    """Run due holding-credit checks. Returns {stats, void_events}."""
    stats = {"checked": 0, "cleared": 0, "voided": 0, "rescheduled": 0, "skipped": 0}
    void_events: list[dict] = []
    with DBConnection() as db:
        due = db.autobuy_credits_due_for_check(limit=limit)

    if not due:
        return {"stats": stats, "void_events": void_events}

    interval = max(1.0, float(interval_hours))
    now = _utc_now()

    for row in due:
        credit_id = int(row["id"])
        email = (row.get("ms_email") or row.get("email") or "").strip()
        password = (row.get("ms_password") or "").strip()
        discord_id = int(row["discord_id"])
        remaining = float(row.get("remaining_usd") or 0)

        if not email or not password:
            logger.warning(
                "autobuy hold check skip credit=%s — missing secured creds for %s",
                credit_id,
                row.get("email"),
            )
            next_at = _fmt_ts(now + timedelta(hours=min(interval, 2.0)))
            with DBConnection() as db:
                db.autobuy_mark_credit_checked(credit_id, next_check_at=next_at)
            stats["skipped"] += 1
            continue

        try:
            status, reason = await check_sold_account(email, password)
        except Exception:
            logger.exception("autobuy hold check crashed credit=%s email=%s", credit_id, email)
            next_at = _fmt_ts(now + timedelta(hours=1))
            with DBConnection() as db:
                db.autobuy_mark_credit_checked(credit_id, next_check_at=next_at)
            stats["skipped"] += 1
            continue

        stats["checked"] += 1

        if status == "bad":
            with DBConnection() as db:
                voided = db.autobuy_void_credit(credit_id, reason or "failed hold check")
            if voided > 0:
                stats["voided"] += 1
                void_events.append(
                    {
                        "discord_id": discord_id,
                        "email": email,
                        "amount_usd": voided or remaining,
                        "reason": reason or "failed hold check",
                    }
                )
                logger.warning(
                    "autobuy voided credit=%s email=%s reason=%s amount=$%.2f",
                    credit_id,
                    email,
                    reason,
                    voided,
                )
            continue

        if status == "unknown":
            next_at = _fmt_ts(now + timedelta(hours=1))
            with DBConnection() as db:
                db.autobuy_mark_credit_checked(credit_id, next_check_at=next_at)
            stats["rescheduled"] += 1
            continue

        available_at = _parse_ts(row.get("available_at"))
        hold_elapsed = available_at is not None and available_at <= now

        if hold_elapsed:
            with DBConnection() as db:
                db.autobuy_mark_credit_checked(credit_id, next_check_at=None, clear=True)
            stats["cleared"] += 1
            logger.info("autobuy cleared credit=%s email=%s", credit_id, email)
        else:
            next_dt = now + timedelta(hours=interval)
            if available_at and next_dt > available_at:
                next_dt = available_at
            with DBConnection() as db:
                db.autobuy_mark_credit_checked(credit_id, next_check_at=_fmt_ts(next_dt))
            stats["rescheduled"] += 1

    return {"stats": stats, "void_events": void_events}
