import base64
import html as html_lib
import json
import logging
import re
from urllib.parse import urljoin

import httpx

from minecraft.retry import TransientMCError, with_retries

log = logging.getLogger(__name__)

_SISU_URL = (
    "https://sisu.xboxlive.com/connect/XboxLive/"
    "?state=login&cobrandId=8058f65d-ce06-4c30-9559-473c9275a65d"
    "&tid=896928775&ru=https://www.minecraft.net/en-us/login&aid=1142970254"
)
_MAX_HOPS = 16


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
    combined = f"{url} {text}".lower()
    return any(
        x in combined
        for x in (
            "proofs/verify",
            "proofs/add",
            "overprotective",
            "frmaddproof",
            "help us protect your account",
        )
    )


def _sso_payload(text: str, base_url: str) -> tuple[str, dict[str, str]] | None:
    """Return (action, fields) for fmHF / NAP-ANON continue forms."""
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
    """Return (urlPost, sFT) for KMSI type=28 pages only."""
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


async def _skip_proofs_interrupt(
    session: httpx.AsyncClient,
    html: str,
    page_url: str,
) -> httpx.Response:
    """Skip account.live.com/proofs/Verify (and similar) during Xbox SSO."""
    skip_url = _skip_url_from_html(html)
    if skip_url:
        log.info("get_xbl: following proofs skip URL → %s", skip_url[:200])
        return await session.get(skip_url, follow_redirects=False)

    action = _extract_form_action(html, page_url)
    fields = _extract_hidden_fields(html)
    if not action:
        raise TransientMCError(f"proofs interrupt missing form action url={page_url[:160]}")

    fields["action"] = "Skip"
    fields.setdefault("iOttText", "")
    proof_opt = re.search(r'name="iProofOptions"[^>]*value="([^"]+)"', html, re.I)
    if not proof_opt:
        proof_opt = re.search(r'value="(OTT\|\|[^"]+)"', html)
    if proof_opt:
        fields["iProofOptions"] = proof_opt.group(1)
    if "canary" not in fields:
        canary = re.search(r'"canary"\s*:\s*"([^"]+)"', html)
        if canary:
            fields["canary"] = canary.group(1)

    log.info("get_xbl: skipping proofs interrupt via POST action=Skip → %s", action[:200])
    return await session.post(
        action,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=fields,
        follow_redirects=False,
    )


async def _follow_sisu(session: httpx.AsyncClient) -> dict | None:
    """Walk sisu → login.live → minecraft.net accessToken.

    Handles KMSI, SSO continue forms, and proofs/Verify skips that otherwise
    produce false ``Unknown (MC check failed)`` labels.
    """
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

        # Redirect into proofs interrupt — fetch then skip
        if location and _is_proofs_interrupt(location):
            log.info("get_xbl: redirect into proofs interrupt → %s", location[:200])
            verify = await session.get(urljoin(page_url, location), follow_redirects=False)
            token = _token_from_response(verify)
            if token:
                return _decode_xbl(token)
            skipped = await _skip_proofs_interrupt(
                session, verify.text or "", str(verify.url)
            )
            token = _token_from_response(skipped)
            if token:
                return _decode_xbl(token)
            loc2 = skipped.headers.get("Location")
            if loc2:
                url = urljoin(str(skipped.url), loc2)
                continue
            # Skip returned another HTML page — keep processing it next hop
            body = skipped.text or ""
            page_url = str(skipped.url)
            status = skipped.status_code
            location = None
            # fall through to HTML handlers below
        elif location:
            url = urljoin(page_url, location)
            log.debug("get_xbl hop %s redirect → %s", hop + 1, url[:180])
            continue

        if status != 200 or not body:
            raise TransientMCError(
                f"sisu hop stuck (status={status} url={url[:160]} no Location)"
            )

        # Already on proofs interrupt HTML
        if _is_proofs_interrupt(page_url, body):
            skipped = await _skip_proofs_interrupt(session, body, page_url)
            token = _token_from_response(skipped)
            if token:
                return _decode_xbl(token)
            loc2 = skipped.headers.get("Location")
            if loc2:
                url = urljoin(str(skipped.url), loc2)
                continue
            raise TransientMCError(
                f"proofs skip did not continue SSO (status={skipped.status_code})"
            )

        sso = _sso_payload(body, page_url)
        if sso:
            action, fields = sso
            # Never blind-post into proofs/Verify as if it were a finish form
            if _is_proofs_interrupt(action):
                log.info(
                    "get_xbl: SSO form targets proofs interrupt — posting then skipping"
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
                if loc2 and not _is_proofs_interrupt(loc2):
                    url = urljoin(str(post.url), loc2)
                    continue
                # Landed on / still on verify page
                verify_html = post.text or ""
                verify_url = str(post.url)
                if loc2 and _is_proofs_interrupt(loc2):
                    verify = await session.get(
                        urljoin(str(post.url), loc2), follow_redirects=False
                    )
                    token = _token_from_response(verify)
                    if token:
                        return _decode_xbl(token)
                    verify_html = verify.text or ""
                    verify_url = str(verify.url)
                skipped = await _skip_proofs_interrupt(session, verify_html, verify_url)
                token = _token_from_response(skipped)
                if token:
                    return _decode_xbl(token)
                loc3 = skipped.headers.get("Location")
                if loc3:
                    url = urljoin(str(skipped.url), loc3)
                    continue
                raise TransientMCError(
                    "sisu proofs/Verify SSO did not yield accessToken after skip"
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
            # Nested continue form
            sso2 = _sso_payload(post.text or "", str(post.url))
            if sso2:
                action2, fields2 = sso2
                if _is_proofs_interrupt(action2):
                    url = action2
                    # Force next iteration to treat as proofs via GET of current... 
                    # Better: set body path by GETting isn't right. Post then skip.
                    post2 = await session.post(
                        action2,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        data=fields2,
                        follow_redirects=False,
                    )
                    skipped = await _skip_proofs_interrupt(
                        session, post2.text or "", str(post2.url)
                    )
                    token = _token_from_response(skipped)
                    if token:
                        return _decode_xbl(token)
                    loc3 = skipped.headers.get("Location") or post2.headers.get("Location")
                    if loc3:
                        url = urljoin(str(skipped.url), loc3)
                        continue
                    raise TransientMCError("nested proofs SSO skip failed")
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


async def _get_xbl_once(session: httpx.AsyncClient) -> dict | None:
    return await _follow_sisu(session)


async def get_xbl(session: httpx.AsyncClient) -> dict | None:
    return await with_retries(
        "get_xbl",
        lambda: _get_xbl_once(session),
        attempts=7,
        base_delay=4.0,
        retry_on_none=False,
    )
