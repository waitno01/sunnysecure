"""Reject problematic account types before they are stored or paid out."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any


def _load_reject_cfg() -> dict:
    try:
        with open("config/config.json", "r") as f:
            cfg = json.load(f)
        autosecure = cfg.get("autosecure") or {}
        reject = autosecure.get("reject") or {}
        return {
            "family_members": reject.get("family_members", True),
            "family_locked": reject.get("family_locked", True),
            "gamepass": reject.get("gamepass", True),
            "underage": reject.get("underage", True),
            "min_age_years": int(reject.get("min_age_years") or 18),
        }
    except Exception:
        return {
            "family_members": True,
            "family_locked": True,
            "gamepass": True,
            "underage": True,
            "min_age_years": 18,
        }


def _parse_birthday(raw: Any) -> date | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in ("failed to get", "unknown", "n/a", "none"):
        return None

    # epoch ms / s
    if re.fullmatch(r"\d{10,13}", text):
        try:
            ts = int(text)
            if ts > 10_000_000_000:
                ts //= 1000
            return datetime.utcfromtimestamp(ts).date()
        except (ValueError, OSError, OverflowError):
            return None

    # /Date(1234567890123)/
    m = re.search(r"/Date\((-?\d+)", text)
    if m:
        try:
            ts = int(m.group(1))
            if abs(ts) > 10_000_000_000:
                ts //= 1000
            return datetime.utcfromtimestamp(ts).date()
        except (ValueError, OSError, OverflowError):
            return None

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            candidate = text[:26] if "T" in fmt else text[:10]
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _age_years(dob: date, today: date | None = None) -> int:
    today = today or date.today()
    years = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return years


def _subs_blob(subs: Any) -> str:
    if not subs:
        return ""
    if isinstance(subs, str):
        return subs.lower()
    try:
        return json.dumps(subs).lower()
    except Exception:
        return str(subs).lower()


def _sub_items(subs: Any, *buckets: str) -> list:
    if not isinstance(subs, dict):
        return []
    out: list = []
    for key in buckets:
        items = subs.get(key) or []
        if isinstance(items, list):
            out.extend(items)
        elif items:
            out.append(items)
    return out


def _dig_str(obj: Any, *paths: tuple[str, ...]) -> list[str]:
    """Collect string values at shallow keys / one-level nested dict paths."""
    found: list[str] = []
    if not isinstance(obj, dict):
        return found
    for path in paths:
        cur: Any = obj
        ok = True
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok and cur not in (None, ""):
            found.append(str(cur))
    return found


def _sub_status_blob(sub: Any) -> str:
    """Status / lifecycle fields only — never marketing CMS blobs."""
    if not isinstance(sub, dict):
        return str(sub).lower()
    parts = _dig_str(
        sub,
        ("status",),
        ("subscriptionStatus",),
        ("state",),
        ("billingStatus",),
        ("renewalStatus",),
        ("statusText",),
        ("statusDescription",),
        ("recurrenceState",),
        ("lifecycleStatus",),
    )
    for key in (
        "expirationDate",
        "expiryDate",
        "endDate",
        "expiresOn",
        "validUntil",
        "nextRenewalDate",
        "renewalDate",
    ):
        if sub.get(key) not in (None, ""):
            parts.append(str(sub.get(key)))
    if "autoRenew" in sub:
        parts.append(f"autorenew={sub.get('autoRenew')}")
    return " ".join(parts).lower()


def _parse_sub_date(raw: Any) -> date | None:
    """Best-effort parse of MS subscription date strings."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {
        "no renewal date",
        "none",
        "null",
        "n/a",
        "",
    }:
        return None
    # ISO / datetime
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
        "%b %d, %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(text.replace("Z", "")[:19], fmt).date()
        except ValueError:
            continue
    # "Expired on Feb 17, 2026"
    m = re.search(
        r"(?:expir\w+\s+on\s+|on\s+)?([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})",
        text,
        re.I,
    )
    if m:
        return _parse_sub_date(m.group(1))
    return None


def _sub_looks_inactive(sub: Any) -> bool:
    """True for expired / canceled / ended listings (should not reject)."""
    status = _sub_status_blob(sub)
    if re.search(
        r"\b(expired|canceled|cancelled|inactive|ended|lapsed|terminated|"
        r"deactivated|disabled|suspended)\b",
        status,
    ):
        return True
    if "expir" in status or ("cancel" in status and "active" not in status):
        return True
    if not isinstance(sub, dict):
        return False
    # Past end / renewal date ⇒ not an active entitlement
    today = date.today()
    for key in (
        "expirationDate",
        "expiryDate",
        "endDate",
        "expiresOn",
        "validUntil",
        "nextRenewalDate",
        "renewalDate",
    ):
        parsed = _parse_sub_date(sub.get(key))
        if parsed is not None and parsed < today:
            return True
    # PaymentInstruments: dead cycles often have autoRenew=false + no renewal date
    if sub.get("autoRenew") is False:
        renewal = str(
            sub.get("nextRenewalDate")
            or sub.get("renewalDate")
            or ""
        ).lower()
        if not renewal or "no renewal" in renewal or renewal in {"none", "null", "n/a"}:
            return True
    return False


def _sub_name_blob(sub: Any) -> str:
    """Product title only — do NOT dump full JSON (upsells mention Game Pass)."""
    if isinstance(sub, str):
        return sub.lower()
    if not isinstance(sub, dict):
        return str(sub).lower()
    parts = _dig_str(
        sub,
        ("name",),
        ("title",),
        ("productName",),
        ("productTitle",),
        ("locTitle",),
        ("localizedName",),
        ("serviceName",),
        ("offerName",),
        ("product",),
        ("product", "name"),
        ("product", "title"),
        ("offer", "name"),
        ("sku", "name"),
    )
    return " ".join(parts).lower()


def _is_gamepass_product(name_blob: str) -> bool:
    """True if the *product title* is Game Pass (not Realms / M365 / upsell copy)."""
    if not name_blob:
        return False
    if re.search(r"\brealms?\b", name_blob):
        return False
    if re.search(r"microsoft\s*365|office\s*365|onedrive|storage", name_blob):
        return False
    return bool(
        re.search(
            r"(xbox\s+)?(pc\s+|console\s+)?"
            r"game\s*pass(\s+(ultimate|standard|core|essential|for\s+pc))?"
            r"|gamepass(\s+ultimate)?",
            name_blob,
        )
    )


def _has_gamepass_subscription(ms: dict) -> bool:
    """True only for *active* Game Pass product — expired/canceled ignored.

    Important: only match product title fields. Full JSON dumps false-positive on
    Realms/M365 cards that embed Game Pass marketing / resubscribe CTAs.
    """
    subs = ms.get("subscriptions") or {}
    if isinstance(subs, str):
        blob = subs.lower()
        if not _is_gamepass_product(blob):
            return False
        if re.search(r"cancel|expir|ended|inactive|resubscribe", blob):
            return False
        return True

    # Never scan canceled (AMC lists expired Ultimate / PC Game Pass there)
    for sub in _sub_items(subs, "active", "commercial"):
        if _sub_looks_inactive(sub):
            continue
        name = _sub_name_blob(sub)
        if _is_gamepass_product(name):
            print(f"[!] - Game Pass reject match on title: {name[:120]!r}")
            return True
    return False


def _has_family_members(ms: dict) -> bool:
    family = ms.get("family") or []
    if isinstance(family, str):
        try:
            family = json.loads(family)
        except Exception:
            return bool(family.strip()) and family.strip().lower() not in ("[]", "null", "none")
    return isinstance(family, list) and len(family) > 0


def rejection_reason(account_info: dict | None, *, cfg: dict | None = None) -> str | None:
    """Return a human reason if this secured account should be rejected, else None."""
    if not account_info or not isinstance(account_info, dict):
        return None
    if account_info.get("failed"):
        return account_info.get("reason") or "Securing failed"

    rules = cfg or _load_reject_cfg()
    ms = account_info.get("microsoft") or {}
    mc = account_info.get("minecraft") or {}

    # Family Locked / child lock markers from login interrupt
    if rules.get("family_locked", True):
        email = str(ms.get("email") or "")
        name = str(mc.get("name") or "")
        if "child locked" in email.lower() or "child locked" in name.lower():
            return "Account is Family Locked (child/parental)."

    if rules.get("family_members", True) and _has_family_members(ms):
        return "Account belongs to a Microsoft Family (has family members)."

    if rules.get("gamepass", True):
        method = str(mc.get("method") or "").lower()
        if "gamepass" in method or "game pass" in method:
            return "Minecraft is Game Pass entitlement (not a purchased Java copy)."
        if _has_gamepass_subscription(ms):
            return "Account has an active Xbox Game Pass subscription."

    if rules.get("underage", True):
        dob = _parse_birthday(ms.get("birthday"))
        if dob is not None:
            min_age = int(rules.get("min_age_years") or 18)
            age = _age_years(dob)
            if age < min_age:
                return f"Account is underage (DOB age {age} < {min_age})."

    return None
