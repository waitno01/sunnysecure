"""Xbox Live SSO for Minecraft — handles CatB overprotective proofs/Verify.

When Microsoft inserts account.live.com/proofs/Verify?mpcxt=CATB during sisu,
Skip often loops. The reliable path (see overprotective5.har) is:

  SendOtt (action=Compliance) → email OTP → VerifyProof
  (sometimes a second SendOtt+OTP when the first verify returns orc=1&rc=1)
"""

from __future__ import annotations

import base64
import html as html_lib
import json
import logging
import re
import time
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx

from minecraft.retry import TransientMCError, with_retries

log = logging.getLogger(__name__)

_SISU_URL = (
    "https://sisu.xboxlive.com/connect/XboxLive/"
    "?state=login&cobrandId=8058f65d-ce06-4c30-9559-473c9275a65d"
    "&tid=896928775&ru=https://www.minecraft.net/en-us/login&aid=1142970254"
)
_MAX_HOPS = 20
_SEND_OTT_URL = "https://account.live.com/API/Proofs/SendOtt"


def _extract_access_token(url_or_text: str) -> str | None:
    m = re.search(r"accessToken=([^&#\"'\s]+)", url_or_text)
    return m.group(1) if m else None


def _extract_hidden_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for tag in re.findall(r"<input[^>]+>", text, re.I):
        name_m = re.search(r'name=["\']([^"\']+)["\']', tag, re.I)
        if not name_m:
            continue
        val_m = re.search(r'value=["\']([^"\']*)["\']', tag, re.I)
        fields[name_m.group(1)] = html_lib.unescape(val_m.group(1)) if val_m else ""
    return fields


def _extract_form_action(text: str, base_url: str) -> str | None:
    for pat in (
        r'<form[^>]*id=["\']frmAddProof["\'][^>]*action=["\']([^"\']+)["\']',
        r'<form[^>]*action=["\']([^"\']+)["\']',
    ):
        m = re.search(pat, text, re.I)
        if m:
            action = html_lib.unescape(m.group(1).replace("&amp;", "&"))
            if action.startswith("http"):
                return action
            return urljoin(base_url, action)
    return None


def _is_proofs_interrupt(url: str, text: str = "") -> bool:
    """True for real proofs pages or auto-submit bridges that POST into them.

    Do NOT scan arbitrary HTML for 'proofs/verify' — oauth20_authorize shims
    embed that URL in a form action and were falsely treated as Verify pages.
    """
    u = (url or "").lower()
    if any(
        x in u
        for x in (
            "proofs/verify",
            "proofs/add",
            "proofs/remind",
            "overprotective",
            "mpcxt=catb",
        )
    ):
        return True
    if text and _is_auto_submit_bridge(text, url):
        return True
    t = (text or "").lower()
    # Body-only signals (avoid oauth pages that merely mention proofs in a form)
    if "login.live.com" in u or "oauth20" in u:
        return False
    return any(
        x in t
        for x in (
            "frmaddproof",
            "help us protect your account",
            "mpcxt=catb",
        )
    )


def _is_catb_verify(url: str, text: str = "") -> bool:
    """True for the real CatB Verify challenge (not remind / oauth shim)."""
    u = (url or "").lower()
    t = (text or "").lower()
    if "proofs/remind" in u:
        return False
    if _is_auto_submit_bridge(text or "", url):
        return False
    if "mpcxt=catb" in u or "mpcxt=catb" in t or "scontext\": \"catb\"" in t or "scontext: 'catb'" in t:
        return "proofs/verify" in u or bool(_find_proof_option(text or ""))
    if "proofs/verify" in u and (
        "overprotective" in t or "scontext" in t and "catb" in t
    ):
        return True
    return False


def _is_live_verify_challenge(url: str, html: str) -> bool:
    """Still on CatB Verify with an OTT option (need another OTP round)."""
    if _is_auto_submit_bridge(html, url):
        return False
    u = (url or "").lower()
    if "proofs/verify" not in u:
        return False
    return bool(_find_proof_option(html) or _cfg_str(html, "sProofData"))


def _is_auto_submit_bridge(html: str, page_url: str = "") -> bool:
    """login.live auto-POST shim (fmHF/DoSubmit) that lands on proofs/Verify.

    These pages mention mpcxt=CATB in the *form action* but have no OTT radios —
    we must POST the form before scraping CatB tokens.
    """
    if not html:
        return False
    low = html.lower()
    def _action_is_proofs(action: str) -> bool:
        a = (action or "").lower()
        return any(
            x in a
            for x in (
                "proofs/verify",
                "proofs/add",
                "proofs/remind",
                "mpcxt=catb",
                "overprotective",
            )
        )

    if "dosubmit()" in low or 'id="fmhf"' in low or "name=\"fmhf\"" in low:
        action = _extract_form_action(html, page_url or "https://login.live.com/") or ""
        return _action_is_proofs(action)
    # Compact auto-post pages with pprid+ipt targeting proofs
    if len(html) < 5000 and "pprid" in low and ("name=\"ipt\"" in low or 'name="ipt"' in low):
        action = _extract_form_action(html, page_url or "https://login.live.com/") or ""
        return _action_is_proofs(action)
    return False


async def _post_auto_submit_bridge(
    session: httpx.AsyncClient,
    html: str,
    page_url: str,
) -> httpx.Response:
    """POST the fmHF/SSO bridge and follow until we have Verify HTML or a token."""
    sso = _sso_payload(html, page_url)
    if not sso:
        raise TransientMCError(
            f"proofs auto-submit bridge missing pprid/ipt fields url={page_url[:160]}"
        )
    action, fields = sso
    log.info("get_xbl: posting proofs auto-submit bridge → %s", action[:200])
    resp = await session.post(
        action,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=fields,
        follow_redirects=False,
    )
    for _ in range(6):
        if _token_from_response(resp):
            return resp
        body = resp.text or ""
        # Landed on real Verify HTML (has sProofData / OTT options)
        if body and not _is_auto_submit_bridge(body, str(resp.url)):
            if _is_proofs_interrupt(str(resp.url), body) or _find_proof_option(body):
                return resp
            if "sProofData" in body or "sNetId" in body:
                return resp
        loc = resp.headers.get("Location")
        if loc:
            resp = await session.get(
                urljoin(str(resp.url), loc), follow_redirects=False
            )
            continue
        # Another nested auto-submit?
        if body and _is_auto_submit_bridge(body, str(resp.url)):
            nested = _sso_payload(body, str(resp.url))
            if nested:
                action2, fields2 = nested
                resp = await session.post(
                    action2,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data=fields2,
                    follow_redirects=False,
                )
                continue
        break
    return resp


def _sso_payload(text: str, base_url: str) -> tuple[str, dict[str, str]] | None:
    fields = _extract_hidden_fields(text)
    action = _extract_form_action(text, base_url)
    if not action:
        return None
    if "pprid" in fields and "NAP" in fields and "ANON" in fields and "t" in fields:
        return action, {
            "pprid": fields["pprid"],
            "NAP": fields["NAP"],
            "ANON": fields["ANON"],
            "t": fields["t"],
        }
    if "pprid" in fields and ("ipt" in fields or "t" in fields):
        return action, fields
    return None


def _kmsi_payload(text: str) -> tuple[str, str] | None:
    page_id = re.search(r'PageID" content="([^"]+)"', text)
    if page_id and page_id.group(1) not in ("i5245", "i5643"):
        return None
    url_m = re.search(r'"urlPost"\s*:\s*"(https://[^"]+post\.srf[^"]*)"', text)
    sft_m = re.search(r'"sFT"\s*:\s*"([^"]+)"', text)
    if url_m and sft_m:
        return url_m.group(1), sft_m.group(1)
    return None


def _skip_url_from_html(text: str) -> str | None:
    for pat in (
        r'"skip"\s*:\s*\{\s*"url"\s*:\s*"([^"]+)"',
        r'"skipUrl"\s*:\s*"([^"]+)"',
        r'"cancel"\s*:\s*\{\s*"url"\s*:\s*"([^"]+)"',
    ):
        m = re.search(pat, text)
        if m:
            return m.group(1).replace("\\u0026", "&").replace("\\/", "/")
    return None


def _decode_xbl(access_token: str) -> dict | None:
    padded = access_token + "=" * ((4 - len(access_token) % 4) % 4)
    try:
        decoded_data = base64.b64decode(padded).decode("utf-8")
        json_data = json.loads(decoded_data)
    except Exception as exc:
        raise TransientMCError(f"accessToken decode failed: {exc}") from exc

    if not isinstance(json_data, list) or not json_data:
        raise TransientMCError("decoded XBL token not a list")

    uhs = json_data[0].get("Item2", {}).get("DisplayClaims", {}).get("xui", [{}])[0].get("uhs")
    xsts = ""
    gtg = None
    for item in json_data:
        if item.get("Item1") == "rp://api.minecraftservices.com/":
            xsts = item.get("Item2", {}).get("Token", "")
        elif item.get("Item1") == "http://xboxlive.com":
            xui = item.get("Item2", {}).get("DisplayClaims", {}).get("xui", [{}])[0]
            if xui:
                gtg = xui.get("gtg")

    if not uhs or not xsts:
        raise TransientMCError("decoded XBL token missing uhs/xsts")

    return {"xbl": f"XBL3.0 x={uhs};{xsts}", "gtg": gtg}


def _token_from_response(resp: httpx.Response) -> str | None:
    for candidate in (
        resp.headers.get("Location") or "",
        str(resp.url),
        resp.text or "",
    ):
        token = _extract_access_token(candidate)
        if token:
            return token
    return None


def _js_string_unescape(raw: str) -> str:
    """Decode JS string escapes used in ServerData (\x2f, \u002f, \\', etc.)."""
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] == "\\" and i + 3 < len(raw) and raw[i + 1] == "x":
            try:
                out.append(chr(int(raw[i + 2 : i + 4], 16)))
                i += 4
                continue
            except ValueError:
                pass
        if raw[i] == "\\" and i + 5 < len(raw) and raw[i + 1] == "u":
            try:
                out.append(chr(int(raw[i + 2 : i + 6], 16)))
                i += 6
                continue
            except ValueError:
                pass
        if raw[i] == "\\" and i + 1 < len(raw):
            out.append(raw[i + 1])
            i += 2
            continue
        out.append(raw[i])
        i += 1
    return "".join(out)


def _cfg_str(html: str, *keys: str) -> str | None:
    for key in keys:
        # JSON / $Config style: "sProofData":"..."
        m = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', html)
        if m:
            raw = m.group(1)
            try:
                return json.loads(f'"{raw}"')
            except Exception:
                return (
                    raw.replace("\\u0026", "&")
                    .replace("\\/", "/")
                    .replace('\\"', '"')
                )
        m = re.search(rf'"{re.escape(key)}"\s*:\s*(\d+)', html)
        if m:
            return m.group(1)
        # ServerData JS style: sProofData: '...'  (single quotes + \x2f escapes)
        m = re.search(rf"(?:^|[,\s{{]){re.escape(key)}\s*:\s*'((?:\\'|[^'])*)'", html)
        if m:
            return _js_string_unescape(m.group(1))
        m = re.search(rf'(?:^|[,\s{{]){re.escape(key)}\s*:\s*"((?:\\.|[^"\\])*)"', html)
        if m:
            return _js_string_unescape(m.group(1))
        m = re.search(rf"(?:^|[,\s{{]){re.escape(key)}\s*:\s*(\d+)", html)
        if m:
            return m.group(1)
    return None


def _find_proof_option(html: str, preferred_email: str | None = None) -> str | None:
    options = re.findall(r'value="(OTT\|\|[^"]+)"', html, re.I)
    if not options:
        m = re.search(r'name="iProofOptions"[^>]*value="([^"]+)"', html, re.I)
        if m:
            options = [m.group(1)]
    if not options:
        return None
    if preferred_email:
        local = preferred_email.split("@", 1)[0].lower()
        domain = preferred_email.split("@", 1)[-1].lower()
        for opt in options:
            parts = opt.split("||")
            obs = (parts[1] if len(parts) > 1 else "").lower()
            if domain in obs and (not local or obs.startswith(local[:2])):
                return opt
            if preferred_email.lower() in opt.lower():
                return opt
    return options[0]


def _destination_from_proof(html: str, proof_opt: str) -> tuple[str, str]:
    """Return (destination, channel) using parseProofData rules."""
    parts = proof_opt.split("||")
    channel = parts[2] if len(parts) > 2 else "Email"
    try:
        idx = int(parts[3]) if len(parts) > 3 else 0
    except ValueError:
        idx = 0

    enc = _cfg_str(html, "sProofData", "encryptedProofData") or ""
    if not enc:
        # Sometimes nested under verifyProof
        m = re.search(
            r'"(?:sProofData|encryptedProofData)"\s*:\s*"((?:\\.|[^"\\])*)"',
            html,
        )
        if m:
            try:
                enc = json.loads(f'"{m.group(1)}"')
            except Exception:
                enc = m.group(1)

    chunks = enc.split("||") if enc else []
    if idx >= len(chunks) or not chunks:
        raise TransientMCError("CatB page missing encrypted proof data for SendOtt")
    raw = unquote(chunks[idx])
    fields = raw.split("|")
    destination = fields[0] if fields else ""
    if not destination:
        raise TransientMCError("CatB encrypted proof destination empty")
    return destination, channel or "Email"


def _scrape_catb_tokens(html: str, page_url: str, security_email: str | None) -> dict:
    proof_opt = _find_proof_option(html, security_email)
    if not proof_opt:
        raise TransientMCError("CatB Verify page has no OTT proof option")

    destination, channel = _destination_from_proof(html, proof_opt)
    fields = _extract_hidden_fields(html)
    form_canary = fields.get("canary") or _cfg_str(html, "canary") or ""
    api_canary = _cfg_str(html, "apiCanary") or form_canary
    netid = _cfg_str(html, "sNetId", "netId", "encryptedNetId") or ""
    action = _cfg_str(html, "sAction") or "Compliance"
    cxt = _cfg_str(html, "sContext", "cxt") or "CatB"
    uaid = _cfg_str(html, "uaid") or ""
    if not uaid:
        qs = parse_qs(urlparse(page_url).query)
        uaid = (qs.get("uaid") or [""])[0]
    scid = int(_cfg_str(html, "scid") or "100146")
    hpgid = int(_cfg_str(html, "hpgid") or "201028")
    uiflvr = int(_cfg_str(html, "uiflvr") or "1001")
    eipt = _cfg_str(html, "eipt") or ""
    tcxt = _cfg_str(html, "tcxt") or ""
    verify_action = _extract_form_action(html, page_url) or page_url

    if not netid:
        raise TransientMCError("CatB Verify page missing sNetId")
    if not api_canary:
        raise TransientMCError("CatB Verify page missing apiCanary")

    return {
        "proof_opt": proof_opt,
        "destination": destination,
        "channel": channel,
        "netid": netid,
        "action": action,
        "cxt": cxt,
        "uaid": uaid,
        "scid": scid,
        "hpgid": hpgid,
        "uiflvr": uiflvr,
        "api_canary": api_canary,
        "form_canary": form_canary or api_canary,
        "eipt": eipt,
        "tcxt": tcxt,
        "verify_action": verify_action,
    }


async def _send_catb_ott(
    session: httpx.AsyncClient,
    tokens: dict,
    page_url: str,
) -> None:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://account.live.com",
        "Referer": page_url,
        "canary": tokens["api_canary"],
        "hpgid": str(tokens["hpgid"]),
        "scid": str(tokens["scid"]),
        "uaid": tokens["uaid"],
        "uiflvr": str(tokens["uiflvr"]),
        "x-ms-apiTransport": "xhr",
        "x-ms-apiVersion": "2",
    }
    if tokens.get("eipt"):
        headers["eipt"] = tokens["eipt"]
    if tokens.get("tcxt"):
        headers["tcxt"] = tokens["tcxt"]

    body = {
        "destination": tokens["destination"],
        "channel": tokens["channel"],
        "proofCountry": "",
        "proofCountryCode": "",
        "action": tokens["action"],
        "netid": tokens["netid"],
        "cxt": tokens["cxt"],
        "uiflvr": tokens["uiflvr"],
        "uaid": tokens["uaid"],
        "scid": tokens["scid"],
        "hpgid": tokens["hpgid"],
    }
    resp = await session.post(
        _SEND_OTT_URL,
        headers=headers,
        content=json.dumps(body),
        follow_redirects=True,
    )
    log.info(
        "get_xbl: CatB SendOtt status=%s hpgid=%s body=%r",
        resp.status_code,
        tokens["hpgid"],
        (resp.text or "")[:200],
    )
    if resp.status_code >= 400:
        raise TransientMCError(f"CatB SendOtt HTTP {resp.status_code}")
    # Refresh apiCanary from response when present
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("apiCanary"):
            tokens["api_canary"] = data["apiCanary"]
    except Exception:
        pass


async def _verify_catb_ott(
    session: httpx.AsyncClient,
    tokens: dict,
    code: str,
) -> httpx.Response:
    data = {
        "proof": tokens["proof_opt"],
        "iProofOptions": tokens["proof_opt"],
        "iOttText": code,
        "action": "VerifyProof",
        "canary": tokens["form_canary"],
        "GeneralVerify": "0",
    }
    return await session.post(
        tokens["verify_action"],
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=data,
        follow_redirects=False,
    )


async def _follow_location(
    session: httpx.AsyncClient,
    resp: httpx.Response,
) -> httpx.Response:
    """Follow a short redirect chain without consuming forever."""
    current = resp
    for _ in range(8):
        token = _token_from_response(current)
        if token:
            return current
        loc = current.headers.get("Location")
        if not loc:
            return current
        url = urljoin(str(current.url), loc)
        current = await session.get(url, follow_redirects=False)
    return current


async def _complete_catb_with_otp(
    session: httpx.AsyncClient,
    html: str,
    page_url: str,
    security_email: str,
) -> httpx.Response:
    """SendOtt → OTP → VerifyProof, repeating once if orc/rc bounce."""
    from securing.utils.cookies.get_email_code import get_email_code

    current_html = html
    current_url = page_url
    last_resp: httpx.Response | None = None

    for round_i in range(1, 4):
        tokens = _scrape_catb_tokens(current_html, current_url, security_email)
        log.info(
            "get_xbl: CatB OTP round %s proof=%s hpgid=%s",
            round_i,
            tokens["proof_opt"][:60],
            tokens["hpgid"],
        )
        since = time.time()
        await _send_catb_ott(session, tokens, current_url)
        code = await get_email_code(security_email, timeout=90, since=since)
        if not code:
            raise TransientMCError(
                f"CatB OTP did not arrive at {security_email} (round {round_i})"
            )
        print(f"[+] - CatB overprotective OTP round {round_i}: {code}")
        last_resp = await _verify_catb_ott(session, tokens, code)
        token = _token_from_response(last_resp)
        if token:
            return last_resp

        loc = last_resp.headers.get("Location") or ""
        followed = await _follow_location(session, last_resp)
        token = _token_from_response(followed)
        if token:
            return followed

        # Still on Verify (orc/rc) — only loop when the real challenge HTML is back
        next_url = loc or str(followed.url)
        next_html = followed.text or ""
        if not next_html.strip() and loc:
            page = await session.get(
                urljoin(str(last_resp.url), loc),
                follow_redirects=True,
            )
            next_html = page.text or ""
            next_url = str(page.url)
            followed = page
            token = _token_from_response(followed)
            if token:
                return followed

        if _is_live_verify_challenge(next_url, next_html):
            current_html = next_html
            current_url = next_url
            log.info(
                "get_xbl: CatB still on Verify after round %s → %s",
                round_i,
                current_url[:160],
            )
            continue

        # Left Verify (oauth / remind / continue) — hop loop continues SSO
        log.info(
            "get_xbl: CatB OTP cleared after round %s → %s",
            round_i,
            next_url[:160],
        )
        return followed

    raise TransientMCError("CatB overprotective OTP exhausted without accessToken")


async def _skip_proofs_remind(
    session: httpx.AsyncClient,
    html: str,
    page_url: str,
) -> httpx.Response:
    """Confirm 'Is your security info still accurate?' (ProofFreshness LooksGood)."""
    fields = _extract_hidden_fields(html)
    canary = fields.get("canary") or _cfg_str(html, "canary", "apiCanary") or ""
    if not canary:
        raise TransientMCError(f"proofs/remind missing canary url={page_url[:160]}")
    action = _extract_form_action(html, page_url) or page_url
    data = {
        "ProofFreshnessAction": fields.get("ProofFreshnessAction") or "LooksGood",
        "canary": canary,
    }
    log.info("get_xbl: proofs/remind LooksGood → %s", action[:200])
    return await session.post(
        action,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=data,
        follow_redirects=False,
    )


async def _skip_proofs_interrupt(
    session: httpx.AsyncClient,
    html: str,
    page_url: str,
) -> httpx.Response:
    if "proofs/remind" in (page_url or "").lower():
        return await _skip_proofs_remind(session, html, page_url)

    skip_url = _skip_url_from_html(html)
    if skip_url:
        log.info("get_xbl: following proofs skip URL → %s", skip_url[:200])
        return await session.get(skip_url, follow_redirects=False)

    action = _extract_form_action(html, page_url)
    fields = _extract_hidden_fields(html)
    if not action:
        # Form may omit action (POST to current URL) — common on remind-like pages
        if fields.get("canary") or fields.get("ProofFreshnessAction"):
            action = page_url
        else:
            raise TransientMCError(
                f"proofs interrupt missing form action url={page_url[:160]}"
            )

    fields["action"] = "Skip"
    fields.setdefault("iOttText", "")
    proof_opt = re.search(r'name="iProofOptions"[^>]*value="([^"]+)"', html, re.I)
    if not proof_opt:
        proof_opt = re.search(r'value="(OTT\|\|[^"]+)"', html)
    if proof_opt:
        fields["iProofOptions"] = proof_opt.group(1)
        fields.setdefault("proof", proof_opt.group(1))
    if "canary" not in fields:
        canary = _cfg_str(html, "canary", "apiCanary")
        if canary:
            fields["canary"] = canary

    log.info("get_xbl: skipping proofs interrupt via POST action=Skip → %s", action[:200])
    return await session.post(
        action,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=fields,
        follow_redirects=False,
    )


async def _resolve_proofs_interrupt(
    session: httpx.AsyncClient,
    html: str,
    page_url: str,
    security_email: str | None,
) -> httpx.Response:
    """Prefer Skip; for CatB fall back to security-email OTP (often needed twice)."""
    # oauth20_authorize often returns an auto-submit fmHF form pointing at
    # proofs/Verify?mpcxt=CATB — that shim has no OTT radios. POST it first.
    if _is_auto_submit_bridge(html, page_url):
        bridged = await _post_auto_submit_bridge(session, html, page_url)
        token = _token_from_response(bridged)
        if token:
            return bridged
        html = bridged.text or ""
        page_url = str(bridged.url)
        loc = bridged.headers.get("Location")
        if loc and (not html.strip() or _is_auto_submit_bridge(html, page_url)):
            bridged = await session.get(
                urljoin(str(bridged.url), loc), follow_redirects=True
            )
            token = _token_from_response(bridged)
            if token:
                return bridged
            html = bridged.text or ""
            page_url = str(bridged.url)
        log.info(
            "get_xbl: proofs bridge materialized → %s (len=%s ott=%s)",
            page_url[:160],
            len(html),
            bool(_find_proof_option(html)),
        )

    # After CatB, MS often sends proofs/remind — LooksGood continues SSO
    if "proofs/remind" in page_url.lower():
        print("[~] - proofs/remind during Xbox SSO — confirming Looks good")
        return await _skip_proofs_remind(session, html, page_url)

    # CatB: Skip is unreliable — go straight to OTP when we have a security email
    # and the real Verify challenge (OTT radios / sProofData) is present.
    if (
        security_email
        and _is_catb_verify(page_url, html)
        and (_find_proof_option(html) or _cfg_str(html, "sProofData"))
    ):
        print("[~] - CatB overprotective during Xbox SSO — completing via security-email OTP")
        return await _complete_catb_with_otp(session, html, page_url, security_email)

    skipped = await _skip_proofs_interrupt(session, html, page_url)
    token = _token_from_response(skipped)
    if token:
        return skipped

    loc = skipped.headers.get("Location") or ""
    body = skipped.text or ""
    # Skip bounced back to Verify / oauth without token — try OTP
    still_blocked = _is_proofs_interrupt(loc, body) or (
        "oauth20_authorize" in loc.lower() and not _extract_access_token(loc)
    )
    if security_email and still_blocked:
        # If Location is Verify, fetch HTML; if oauth, Skip failed — re-fetch verify if needed
        if _is_proofs_interrupt(loc):
            page = await session.get(urljoin(str(skipped.url), loc), follow_redirects=True)
            print(
                "[~] - CatB Skip bounced — completing via security-email OTP"
            )
            return await _complete_catb_with_otp(
                session, page.text or "", str(page.url), security_email
            )
        if _is_proofs_interrupt(page_url, html):
            print("[~] - proofs Skip ineffective — completing via security-email OTP")
            return await _complete_catb_with_otp(session, html, page_url, security_email)

    return skipped


async def _follow_sisu(
    session: httpx.AsyncClient,
    security_email: str | None = None,
) -> dict | None:
    url = _SISU_URL

    for hop in range(_MAX_HOPS):
        resp = await session.get(url, follow_redirects=False)
        status = resp.status_code
        location = resp.headers.get("Location")
        body = resp.text or ""
        page_url = str(resp.url)

        token = _token_from_response(resp)
        if token:
            return _decode_xbl(token)

        if status in (429, 500, 502, 503, 504):
            raise TransientMCError(f"sisu hop status {status}", status=status)

        if location and _is_proofs_interrupt(location):
            log.info("get_xbl: redirect into proofs interrupt → %s", location[:200])
            verify = await session.get(urljoin(page_url, location), follow_redirects=False)
            token = _token_from_response(verify)
            if token:
                return _decode_xbl(token)
            # May be another redirect to the HTML page
            vloc = verify.headers.get("Location")
            if vloc and not (verify.text or "").strip():
                verify = await session.get(
                    urljoin(str(verify.url), vloc), follow_redirects=True
                )
            resolved = await _resolve_proofs_interrupt(
                session,
                verify.text or "",
                str(verify.url),
                security_email,
            )
            token = _token_from_response(resolved)
            if token:
                return _decode_xbl(token)
            loc2 = resolved.headers.get("Location")
            if loc2:
                url = urljoin(str(resolved.url), loc2)
                continue
            body = resolved.text or ""
            page_url = str(resolved.url)
            status = resolved.status_code
            location = None
        elif location:
            url = urljoin(page_url, location)
            log.debug("get_xbl hop %s redirect → %s", hop + 1, url[:180])
            continue

        if status != 200 or not body:
            raise TransientMCError(
                f"sisu hop stuck (status={status} url={url[:160]} no Location)"
            )

        if _is_proofs_interrupt(page_url, body):
            resolved = await _resolve_proofs_interrupt(
                session, body, page_url, security_email
            )
            token = _token_from_response(resolved)
            if token:
                return _decode_xbl(token)
            loc2 = resolved.headers.get("Location")
            if loc2:
                url = urljoin(str(resolved.url), loc2)
                continue
            # Resolver may return oauth/continue HTML — keep hopping
            body = resolved.text or ""
            page_url = str(resolved.url)
            if _is_proofs_interrupt(page_url, body) and not _sso_payload(body, page_url):
                raise TransientMCError(
                    f"proofs resolve did not continue SSO (status={resolved.status_code} "
                    f"url={page_url[:160]})"
                )
            # Fall through to SSO / KMSI handlers with the new body

        sso = _sso_payload(body, page_url)
        if sso:
            action, fields = sso
            if _is_proofs_interrupt(action):
                log.info(
                    "get_xbl: SSO form targets proofs interrupt — posting then resolving"
                )
                post = await session.post(
                    action,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data=fields,
                    follow_redirects=False,
                )
                token = _token_from_response(post)
                if token:
                    return _decode_xbl(token)
                loc2 = post.headers.get("Location")
                verify_html = post.text or ""
                verify_url = str(post.url)
                if loc2 and _is_proofs_interrupt(loc2):
                    verify = await session.get(
                        urljoin(str(post.url), loc2), follow_redirects=True
                    )
                    token = _token_from_response(verify)
                    if token:
                        return _decode_xbl(token)
                    verify_html = verify.text or ""
                    verify_url = str(verify.url)
                elif loc2 and not _is_proofs_interrupt(loc2):
                    url = urljoin(str(post.url), loc2)
                    continue
                resolved = await _resolve_proofs_interrupt(
                    session, verify_html, verify_url, security_email
                )
                token = _token_from_response(resolved)
                if token:
                    return _decode_xbl(token)
                loc3 = resolved.headers.get("Location")
                if loc3:
                    url = urljoin(str(resolved.url), loc3)
                    continue
                raise TransientMCError(
                    "sisu proofs/Verify SSO did not yield accessToken after resolve"
                )

            log.info("get_xbl: submitting SSO continue form → %s", action[:180])
            post = await session.post(
                action,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=fields,
                follow_redirects=False,
            )
            token = _token_from_response(post)
            if token:
                return _decode_xbl(token)
            loc2 = post.headers.get("Location")
            if loc2:
                url = urljoin(str(post.url), loc2)
                continue
            sso2 = _sso_payload(post.text or "", str(post.url))
            if sso2:
                action2, fields2 = sso2
                if _is_proofs_interrupt(action2):
                    post2 = await session.post(
                        action2,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        data=fields2,
                        follow_redirects=False,
                    )
                    resolved = await _resolve_proofs_interrupt(
                        session,
                        post2.text or "",
                        str(post2.url),
                        security_email,
                    )
                    token = _token_from_response(resolved)
                    if token:
                        return _decode_xbl(token)
                    loc3 = resolved.headers.get("Location") or post2.headers.get(
                        "Location"
                    )
                    if loc3:
                        url = urljoin(str(resolved.url), loc3)
                        continue
                    raise TransientMCError("nested proofs SSO resolve failed")
                post2 = await session.post(
                    action2,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data=fields2,
                    follow_redirects=False,
                )
                token = _token_from_response(post2)
                if token:
                    return _decode_xbl(token)
                loc3 = post2.headers.get("Location")
                if loc3:
                    url = urljoin(str(post2.url), loc3)
                    continue
            raise TransientMCError(
                f"sisu SSO form did not yield accessToken (status={post.status_code})"
            )

        kmsi = _kmsi_payload(body)
        if kmsi:
            url_post, sft = kmsi
            log.info("get_xbl: KMSI finish on Xbox SSO bridge")
            post = await session.post(
                url_post,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=f"PPFT={sft}&canary=&LoginOptions=3&type=28&hpgrequestid=&ctx=",
                follow_redirects=False,
            )
            token = _token_from_response(post)
            if token:
                return _decode_xbl(token)
            loc2 = post.headers.get("Location")
            if loc2:
                url = urljoin(str(post.url), loc2)
                continue
            raise TransientMCError("sisu KMSI did not yield accessToken")

        page_id = re.search(r'PageID" content="([^"]+)"', body)
        title_m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        title = re.sub(r"\s+", " ", title_m.group(1)).strip()[:80] if title_m else "?"
        raise TransientMCError(
            f"sisu hop got HTML without Location/form "
            f"(status={status} pageId={(page_id.group(1) if page_id else None)!r} "
            f"title={title!r} url={page_url[:160]})"
        )

    raise TransientMCError(f"sisu exceeded {_MAX_HOPS} hops without accessToken")


async def _get_xbl_once(
    session: httpx.AsyncClient,
    security_email: str | None = None,
) -> dict | None:
    return await _follow_sisu(session, security_email=security_email)


async def get_xbl(
    session: httpx.AsyncClient,
    security_email: str | None = None,
) -> dict | None:
    return await with_retries(
        "get_xbl",
        lambda: _get_xbl_once(session, security_email=security_email),
        attempts=7,
        base_delay=4.0,
        retry_on_none=False,
    )
