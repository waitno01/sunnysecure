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


def _has_gamepass_subscription(ms: dict) -> bool:
    subs = ms.get("subscriptions") or {}
    if isinstance(subs, str):
        blob = subs.lower()
    else:
        blob = " ".join(
            _subs_blob(subs.get(k))
            for k in ("active", "canceled", "commercial")
            if isinstance(subs, dict)
        )
    return bool(
        re.search(r"game\s*pass|gamepass|xbox\s*game\s*pass|pc\s*game\s*pass", blob)
    )


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
            return "Account has an active/listed Xbox Game Pass subscription."

    if rules.get("underage", True):
        dob = _parse_birthday(ms.get("birthday"))
        if dob is not None:
            min_age = int(rules.get("min_age_years") or 18)
            age = _age_years(dob)
            if age < min_age:
                return f"Account is underage (DOB age {age} < {min_age})."

    return None
