"""Populate owner info from AMCSecAuthJWT when profile API 401s."""

from __future__ import annotations

import base64
import json
import logging

import httpx

from securing.utils.cookies.safe_cookies import get_cookie

log = logging.getLogger(__name__)


def _b64url_json(segment: str) -> dict | None:
    try:
        padded = segment + "=" * ((4 - len(segment) % 4) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return None


def owner_info_from_amc_jwt(session: httpx.AsyncClient) -> dict:
    """Decode AMCSecAuthJWT claims into the personal-info shape we store.

    Live accounts often 401 on ``/profile/api/v1/personal-info`` even with a
    valid AMC JWT (MSAL silent bridge never finishes in httpx). The JWT itself
    already carries given_name / family_name / birthdate / ctry.
    """
    raw = get_cookie(session, "AMCSecAuthJWT")
    if not raw or raw.count(".") < 2:
        return {}
    payload = _b64url_json(raw.split(".")[1])
    if not isinstance(payload, dict):
        return {}

    first = payload.get("given_name") or ""
    last = payload.get("family_name") or ""
    full = payload.get("name") or (" ".join(p for p in (first, last) if p).strip())
    birthday = payload.get("birthdate") or payload.get("birthday")
    region = payload.get("ctry") or payload.get("country")
    lang = payload.get("xms_pl") or payload.get("locale")

    out = {
        "firstName": first or None,
        "lastName": last or None,
        "fullName": full or None,
        "birthday": birthday,
        "region": region,
        "msaDisplayLanguage": lang,
        "signInEmail": payload.get("email") or payload.get("preferred_username"),
        "_from_amc_jwt": True,
    }
    # Drop empty-only dicts
    if not any(out.get(k) for k in ("firstName", "lastName", "fullName", "birthday", "signInEmail")):
        return {}
    log.info(
        "owner_info_from_amc_jwt: %s %s dob=%s region=%s",
        out.get("firstName"),
        out.get("lastName"),
        out.get("birthday"),
        out.get("region"),
    )
    print(
        f"[+] - Owner info from AMC JWT "
        f"({out.get('firstName')} {out.get('lastName')}, {out.get('birthday')}, {out.get('region')})"
    )
    return out
