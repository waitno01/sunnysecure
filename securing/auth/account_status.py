import json
import re

from securing.auth.check_locked import check_locked

# Keep patterns specific — bare "blocked" matches template strings like
# strFedInviteBlockedMsg on every normal login page (false positive).
_LOCK_HTML_PATTERNS: list[tuple[str, str]] = [
    (r"account\s+has\s+been\s+locked", "Account is locked by Microsoft"),
    (r"your\s+account\s+has\s+been\s+suspended", "Account is suspended"),
    (r"account\s+is\s+locked", "Account is locked by Microsoft"),
    (r"isaccountsuspended|account\s+suspended", "Account is suspended"),
    (r"phone\s+verification\s+required|isphonelocked", "Account is phone-locked"),
    (r"we\s+noticed\s+some\s+unusual\s+activity", "Account flagged for unusual activity"),
    (r"violated\s+our\s+terms", "Account may be restricted (ToS/abuse)"),
    (r"account\s+is\s+blocked\s+from\s+signing\s+in|restricted\s+from\s+signing\s+in", "Account is blocked from signing in"),
    (r'"isAccountBlocked"\s*:\s*true', "Account is blocked from signing in"),
]


def lock_reason_from_html(html: str | None) -> str | None:
    if not html:
        return None
    for pattern, reason in _LOCK_HTML_PATTERNS:
        if re.search(pattern, html, re.I):
            return reason
    return None


def lock_reason_from_check_api(info: dict | None) -> str | None:
    if not info:
        return None

    status_code = info.get("StatusCode")
    if status_code is None or status_code >= 500:
        return None

    value_raw = info.get("Value")
    if not value_raw:
        return None

    try:
        value_data = json.loads(value_raw)
        status = value_data.get("status", {})
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

    if status.get("notFound") or status.get("doesAccountExist") is False:
        return "Account does not exist or email is invalid"

    if status.get("isAccountSuspended"):
        reason = status.get("reasonForAccountSuspension") or ""
        if reason:
            return f"Account is suspended by Microsoft ({reason})"
        return "Account is suspended/locked by Microsoft"

    if status.get("isPhoneLocked"):
        return "Account is phone-locked (phone verification required)"

    if status.get("isAccountBlocked"):
        return "Account is blocked from signing in"

    if status.get("isAccountInLostProofState"):
        return "Account is in lost-proof state (recovery proofs missing)"

    if status.get("isUnFamiliarLocationBlockSet"):
        return "Account is blocked due to unfamiliar location"

    if status.get("isAccountCompromised"):
        return "Account is flagged as compromised by Microsoft"

    # isIssuePresent / isAccountInFailedLoginState are soft flags (often from
    # recent failed OTP attempts) — do not treat as locked.
    return None


async def get_account_lock_reason(email: str, login_html: str | None = None) -> str | None:
    html_reason = lock_reason_from_html(login_html)
    if html_reason:
        return html_reason

    api_info = await check_locked(email)
    return lock_reason_from_check_api(api_info)
