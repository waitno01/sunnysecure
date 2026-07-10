from database.database import DBConnection
import asyncio
import re
import time

# Privacy-statement / footer noise that looks like a 6-digit OTP
_FALSE_OTP = frozenset({"521839", "98052"})

_OTP_PATTERNS = (
    r"Security code:\s*(\d{6,8})",
    r"single-use code is:\s*(\d{6,8})",
    r"Your single-use code is:\s*(\d{6,8})",
    r"verification code[:\s]+(\d{6,8})",
    r"code is:\s*(\d{6,8})",
    r"\b(\d{6,8})\b",
)

_SKIP_SUBJECT = (
    "unusual sign-in",
    "unusual activity",
    "security notification",
    "new sign-in",
)


def _extract_otp(body: str) -> str | None:
    if not body:
        return None
    for pat in _OTP_PATTERNS:
        for m in re.finditer(pat, body, re.I):
            code = m.group(1)
            if code in _FALSE_OTP:
                continue
            # Real MS OTCs are 6–8 digits; reject obvious non-codes
            if len(code) < 6:
                continue
            return code
    return None


def _is_skippable_notification(subject: str | None, body: str) -> bool:
    subj = (subject or "").lower()
    if any(s in subj for s in _SKIP_SUBJECT):
        return True
    # Unusual-activity bodies never contain a real OTC line
    if "unusual about a recent sign-in" in (body or "").lower():
        return True
    return False


async def get_email_code(
    mail: str,
    timeout: float = 120,
    *,
    since: float | None = None,
) -> str | None:
    """Wait for a Microsoft OTP at ``mail``.

    Ignores security-notification mail and footer LinkId false-positives
    (e.g. ``521839`` from the Privacy Statement URL) that previously caused
    ``That code didn't work`` failures.

    If ``since`` is set (unix timestamp), only mail with ``received_at`` at/after
    that time is considered — avoids consuming a pre-challenge login OTP and
    then waiting forever for a proofs MFA code that never arrives.
    """
    deadline = time.monotonic() + timeout
    mail_l = (mail or "").lower().strip()
    since_cutoff = None
    if since is not None:
        # SQLite CURRENT_TIMESTAMP is UTC "YYYY-MM-DD HH:MM:SS"
        since_cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(since - 2))

    while time.monotonic() < deadline:
        with DBConnection() as db:
            if since_cutoff:
                rows = db.cursor.execute(
                    """
                    SELECT id, body, subject FROM `received_emails`
                    WHERE lower(to_address) = ? AND consumed = 0
                      AND received_at >= ?
                    ORDER BY id DESC
                    LIMIT 8
                    """,
                    (mail_l, since_cutoff),
                ).fetchall()
            else:
                rows = db.cursor.execute(
                    """
                    SELECT id, body, subject FROM `received_emails`
                    WHERE lower(to_address) = ? AND consumed = 0
                    ORDER BY id DESC
                    LIMIT 8
                    """,
                    (mail_l,),
                ).fetchall()

        for email_id, body, subject in rows:
            if _is_skippable_notification(subject, body or ""):
                with DBConnection() as db:
                    db.mark_used(email_id)
                continue

            code = _extract_otp(body or "")
            if code:
                with DBConnection() as db:
                    db.mark_used(email_id)
                return code

            # Body has no usable OTP — burn it so we don't spin forever
            # (e.g. marketing / empty). Keep waiting for a real code mail.
            if body and len(body) > 40:
                with DBConnection() as db:
                    db.mark_used(email_id)

        await asyncio.sleep(0.8)

    return None
