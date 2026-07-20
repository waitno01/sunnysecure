"""Force-set Microsoft account password after RecoverUser flake."""

from __future__ import annotations

import logging
import re

import httpx

from securing.auth.initial_session import get_session
from securing.utils.proxy import close_session
from securing.utils.security.change_password import change_password_authenticated
from securing.utils.security.password_gen import generate_ms_password
from securing.utils.security.recovery import recover, verify_password_works

logger = logging.getLogger(__name__)

_UNVERIFIED_RE = re.compile(r"\s*\(UNVERIFIED[^)]*\)\s*$")


def strip_unverified(password: str | None) -> str:
    return _UNVERIFIED_RE.sub("", password or "").strip()


def _login_email(ms: dict) -> str:
    """Prefer current primary — original alias is often deleted after replace."""
    return (
        str(ms.get("email") or "").strip()
        or str(ms.get("original_email") or "").strip()
    )


async def _fresh_verify(email: str, password: str, *, settle_delay: float) -> str:
    """Verify on a clean login.live.com session (not the authenticated jar)."""
    probe = get_session()
    try:
        return await verify_password_works(
            probe, email, password, settle_delay=settle_delay
        )
    finally:
        await close_session(probe)


async def force_password_after_recover(
    session: httpx.AsyncClient,
    *,
    email: str,
    security_email: str,
    recovery_code: str,
    preferred_password: str | None = None,
    max_attempts: int = 5,
) -> tuple[str, str, bool]:
    """Retry RecoverUser until the password verifies, or attempts are exhausted.

    RecoverUser can return a new recovery code + attach security email while
    silently ignoring the ``password`` field. Format is not the issue (mixed
    case alnum 14+ is fine — live logs show the same format both OK and BAD).
    MS just flakes. Re-running RecoverUser with the *new* recovery code forces
    another password write.

    Returns ``(password, recovery_code, verified_ok)``.
    """
    pwd = strip_unverified(preferred_password) or generate_ms_password(16)
    rc = (recovery_code or "").strip()
    if not rc or not email or not security_email:
        return pwd, rc, False

    for attempt in range(1, max_attempts + 1):
        # Fresh password each attempt — avoid MS caching an ignored value
        if attempt > 1 or not preferred_password:
            pwd = generate_ms_password(16)
        print(
            f"[~] - Force password via RecoverUser "
            f"(attempt {attempt}/{max_attempts}, len={len(pwd)})..."
        )
        try:
            new_rc = await recover(session, email, rc, security_email, pwd)
        except Exception as exc:
            logger.exception("force password RecoverUser raised: %s", exc)
            print(f"[X] - Force password RecoverUser error: {exc.__class__.__name__}")
            continue

        if not new_rc or new_rc == "invalid":
            print("[X] - Force password RecoverUser soft-failed")
            continue

        rc = new_rc
        # Fresh session — avoid cookie pollution / rate-limit from prior verifies
        status = await _fresh_verify(email, pwd, settle_delay=8.0)
        print(f"[~] - Force password verify => {status}")
        if status == "ok":
            print("[+] - Password forced OK after RecoverUser retry")
            return pwd, rc, True
        if status == "unknown":
            # Soft/rate-limit — longer settle then same pwd once more (no new RecoverUser)
            status2 = await _fresh_verify(email, pwd, settle_delay=15.0)
            print(f"[~] - Force password delayed re-check => {status2}")
            if status2 == "ok":
                print("[+] - Password forced OK after delayed re-check")
                return pwd, rc, True
            # Stay on this password; next loop will RecoverUser again

    print("[X] - Could not force password to stick after RecoverUser retries")
    return pwd, rc, False


async def ensure_password_verified(
    session: httpx.AsyncClient,
    account_info: dict,
    *,
    force_if_unverified: bool = True,
    force_if_bad: bool = True,
) -> bool:
    """Verify microsoft.password; ChangePassword / RecoverUser if bad / UNVERIFIED.

    Mutates ``account_info["microsoft"]`` in place.
    Returns True if password is verified (or verify inconclusive / unknown).
    Returns False only when verify is hard-bad and force retries exhausted.
    """
    ms = account_info.get("microsoft") or {}
    raw = str(ms.get("password") or "")
    clean = strip_unverified(raw)
    marked = "UNVERIFIED" in raw

    email = _login_email(ms)
    sec = str(ms.get("security_email") or "").strip()
    rc = str(ms.get("recovery_code") or "").strip()

    if not clean or not email:
        return not marked

    # CRITICAL: never verify on the authenticated account.live.com jar —
    # login.live.com returns inconclusive / rate-limit noise and used to
    # trigger RecoverUser spirals that left passwords marked UNVERIFIED.
    status = await _fresh_verify(email, clean, settle_delay=4.0)
    print(f"[~] - ensure_password_verified => {status} (email={email})")

    if status == "ok":
        ms["password"] = clean
        account_info["microsoft"] = ms
        return True

    if status == "unknown":
        # Rate-limit / soft-block — one longer settle before deciding
        status = await _fresh_verify(email, clean, settle_delay=12.0)
        print(f"[~] - ensure_password_verified delayed => {status}")
        if status == "ok":
            ms["password"] = clean
            account_info["microsoft"] = ms
            return True
        if status == "unknown" and not marked:
            return True
        # marked + still unknown: try ChangePassword below (don't hard-reject yet)

    if status not in ("bad", "unknown") and not marked:
        return True

    if status == "bad" or marked:
        if not force_if_bad and not (marked and force_if_unverified):
            ms["password"] = f"{clean} (UNVERIFIED — may not work)"
            account_info["microsoft"] = ms
            return False

        # 1) Authenticated ChangePassword (OTP session already elevated).
        # Do NOT send currentPassword first — RecoverUser often ignored the
        # password field so `clean` is not the real current credential.
        pwd = clean or generate_ms_password(16)
        if force_if_unverified or force_if_bad:
            print("[~] - Trying authenticated ChangePassword…")
            changed = await change_password_authenticated(session, pwd)
            if not changed and clean:
                print("[~] - ChangePassword retry with currentPassword field…")
                changed = await change_password_authenticated(
                    session, pwd, current_password=clean
                )
            if changed:
                status2 = await _fresh_verify(email, pwd, settle_delay=6.0)
                print(f"[~] - Post-ChangePassword verify => {status2}")
                if status2 == "ok":
                    ms["password"] = pwd
                    account_info["microsoft"] = ms
                    return True
                if status2 == "unknown":
                    status3 = await _fresh_verify(email, pwd, settle_delay=12.0)
                    print(f"[~] - Post-ChangePassword delayed => {status3}")
                    if status3 == "ok":
                        ms["password"] = pwd
                        account_info["microsoft"] = ms
                        return True
                # Brand-new password once more via ChangePassword
                pwd2 = generate_ms_password(16)
                print("[~] - ChangePassword retry with fresh password…")
                if await change_password_authenticated(session, pwd2):
                    status4 = await _fresh_verify(email, pwd2, settle_delay=8.0)
                    print(f"[~] - Post-ChangePassword(2) verify => {status4}")
                    if status4 == "ok":
                        ms["password"] = pwd2
                        account_info["microsoft"] = ms
                        return True
                    if status4 != "bad":
                        pwd = pwd2

        # 2) One RecoverUser force only — more attempts just rate-limit login.live.com
        if sec and rc and rc not in {"Couldn't Change!", "Failed to generate"}:
            forced_pwd, new_rc, ok = await force_password_after_recover(
                session,
                email=email,
                security_email=sec,
                recovery_code=rc,
                preferred_password=pwd or None,
                max_attempts=1,
            )
            ms["recovery_code"] = new_rc
            rc = new_rc
            if ok:
                ms["password"] = forced_pwd
                account_info["microsoft"] = ms
                return True
            pwd = forced_pwd

        # 3) Still unverified — if recovery code is valid, keep clean password + RC
        # so the sell filter can allow (buyer can reclaim). Otherwise mark UNVERIFIED.
        rc_norm = str(ms.get("recovery_code") or rc or "").strip().upper().replace(" ", "")
        rc_ok = bool(re.fullmatch(r"[A-Z0-9]{5}(?:-[A-Z0-9]{5}){4}", rc_norm))
        if rc_ok:
            print(
                "[!] - Password still unverified after ChangePassword — "
                "keeping recovery code for buyer reclaim"
            )
            ms["password"] = pwd
            account_info["microsoft"] = ms
            return True

        ms["password"] = f"{pwd} (UNVERIFIED — may not work)"
        account_info["microsoft"] = ms
        return False

    return True


async def try_clear_unverified_password(
    session: httpx.AsyncClient,
    account_info: dict,
) -> bool:
    """If microsoft.password is UNVERIFIED (or verify-bad), retry until verified."""
    return await ensure_password_verified(
        session,
        account_info,
        force_if_unverified=True,
        force_if_bad=True,
    )
