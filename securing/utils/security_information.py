import logging
import html
import re
from urllib.parse import urljoin, unquote

import httpx

_PROOFS_URL = "https://account.live.com/proofs/Manage/additional"
_MAX_BRIDGE_HOPS = 10


def _title(text: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.DOTALL)
    if not m:
        return "(no title)"
    return re.sub(r"\s+", " ", m.group(1)).strip()[:120]


def _find_t0(text: str) -> re.Match | None:
    return re.search(r"var\s+t0\s*=\s*(\{.*?\});", text, re.DOTALL)


def _page_debug(text: str, *, url: str = "", status: int | None = None) -> str:
    lower = text.lower()
    flags = []
    if _find_t0(text):
        flags.append("has_t0")
    if "object moved" in lower:
        flags.append("object_moved")
    if "fmhf" in lower:
        flags.append("fmHF")
    if 'name="pprid"' in lower or "name='pprid'" in lower:
        flags.append("pprid")
    if 'name="nap"' in lower:
        flags.append("NAP")
    if 'name="anon"' in lower:
        flags.append("ANON")
    if 'name="ipt"' in lower:
        flags.append("ipt")
    if "jsdisabled.srf" in lower:
        flags.append("jsDisabled_noscript")
    if "help us protect" in lower:
        flags.append("help_protect")
    if "urlpost" in lower:
        flags.append("urlPost")
    if '"sft"' in lower or "sfttag" in lower:
        flags.append("sFT")
    action = re.search(r'action="([^"]+)"', text, re.I)
    page_id = re.search(r'PageID" content="([^"]+)"', text)
    return (
        f"status={status} url={url!s} title={_title(text)!r} "
        f"pageId={(page_id.group(1) if page_id else None)!r} "
        f"flags={flags} action={(action.group(1)[:180] if action else None)!r} "
        f"len={len(text)} snippet={text[:500]!r}"
    )


def _object_moved_href(text: str) -> str | None:
    if "object moved" not in text.lower():
        return None
    m = re.search(r'href="([^"]+)"', text, re.I)
    if not m:
        return None
    return html.unescape(m.group(1).replace("&amp;", "&"))


def _meta_refresh_url(text: str) -> str | None:
    """Return meta-refresh URL, ignoring noscript jsDisabled dead-ends."""
    for m in re.finditer(
        r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\']?\d+\s*;\s*URL=([^"\'>\s]+)',
        text,
        re.I,
    ):
        url = html.unescape(m.group(1).replace("&amp;", "&"))
        if "jsdisabled.srf" in url.lower():
            continue
        # Prefer refreshes outside <noscript> — skip if this match sits in noscript
        start = m.start()
        noscript_open = text.rfind("<noscript", 0, start)
        noscript_close = text.rfind("</noscript>", 0, start)
        if noscript_open > noscript_close:
            continue
        return url
    return None


def _extract_hidden_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for tag in re.findall(r"<input[^>]+>", text, re.I):
        name_m = re.search(r'name=["\']([^"\']+)["\']', tag, re.I)
        if not name_m:
            continue
        val_m = re.search(r'value=["\']([^"\']*)["\']', tag, re.I)
        fields[name_m.group(1)] = html.unescape(val_m.group(1)) if val_m else ""
    return fields


def _extract_form_action(text: str, base_url: str = "") -> str | None:
    m = re.search(r'<form[^>]*action=["\']([^"\']+)["\']', text, re.I)
    if not m:
        return None
    action = html.unescape(m.group(1).replace("&amp;", "&"))
    if action.startswith("http"):
        return action
    return urljoin(base_url or "https://login.live.com/", action)


def _sso_fields(text: str) -> tuple[dict[str, str] | None, list[str]]:
    action = _extract_form_action(text)
    fields = _extract_hidden_fields(text)
    needed = ("pprid", "NAP", "ANON", "t")
    missing = [k for k in needed if k not in fields or fields[k] == ""]
    if not action:
        missing.insert(0, "action")
    if missing:
        return None, missing
    return {
        "action": action,
        "pprid": fields["pprid"],
        "NAP": fields["NAP"],
        "ANON": fields["ANON"],
        "t": fields["t"],
    }, []


def _extract_url_post_sft(text: str) -> tuple[str | None, str | None]:
    url_post = None
    for pat in (
        r'"urlPost"\s*:\s*"(https://login\.live\.com/ppsecure/post\.srf[^"]+)"',
        r'"urlPost"\s*:\s*"(https://[^"]+post\.srf[^"]+)"',
        r'action="(https://login\.live\.com/ppsecure/post\.srf[^"]*)"',
    ):
        m = re.search(pat, text)
        if m:
            url_post = m.group(1)
            break

    sft = None
    m = re.search(r'"sFT"\s*:\s*"([^"]+)"', text)
    if m:
        sft = m.group(1)
    if not sft:
        m = re.search(r'"sFTTag"\s*:\s*"((?:\\.|[^"\\])*)"', text)
        if m:
            tag = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
            vm = re.search(r'value="([^"]+)"', tag)
            if vm:
                sft = vm.group(1)
    if not sft:
        m = re.search(r'name="PPFT"[^>]*value="([^"]+)"', text, re.I)
        if m:
            sft = m.group(1)
    return url_post, sft


def _wreply_from_url(url: str) -> str | None:
    m = re.search(r"[?&]wreply=([^&]+)", url, re.I)
    if not m:
        return None
    return unquote(m.group(1))


async def _get(session: httpx.AsyncClient, url: str) -> httpx.Response:
    return await session.get(url, follow_redirects=True)


async def _post_form(
    session: httpx.AsyncClient,
    action: str,
    data: dict[str, str],
) -> httpx.Response:
    return await session.post(
        url=action,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=data,
        follow_redirects=True,
    )


async def _bridge_to_proofs(
    session: httpx.AsyncClient,
    text: str,
    url: str,
    status: int | None,
) -> tuple[str, str, int | None]:
    """Follow Object-moved / forms / SSO / KMSI until t0 or give up.

    Never follows noscript jsDisabled.srf — that is a JS-required dead end.
    """
    current = text
    current_url = url
    current_status = status

    for hop in range(_MAX_BRIDGE_HOPS):
        if _find_t0(current):
            logging.info(
                "security_information: found t0 after %s bridge hop(s) (%s)",
                hop,
                _page_debug(current, url=current_url, status=current_status),
            )
            return current, current_url, current_status

        # Already on the useless jsDisabled page — bounce back to proofs / wreply
        if "jsdisabled.srf" in current_url.lower():
            wreply = _wreply_from_url(current_url)
            target = wreply or _PROOFS_URL
            logging.warning(
                "security_information: landed on jsDisabled — recovering via %s",
                target[:240],
            )
            resp = await _get(session, target)
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            continue

        logging.info(
            "security_information: bridge hop %s/%s — %s",
            hop + 1,
            _MAX_BRIDGE_HOPS,
            _page_debug(current, url=current_url, status=current_status),
        )

        moved = _object_moved_href(current)
        if moved and "jsdisabled.srf" not in moved.lower():
            logging.info("security_information: following Object moved → %s", moved[:240])
            resp = await _get(session, moved)
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            continue

        # Prefer real forms over meta-refresh (noscript refresh points at jsDisabled)
        sso, missing = _sso_fields(current)
        if sso:
            logging.info(
                "security_information: posting SSO continue form action=%s",
                sso["action"][:240],
            )
            resp = await _post_form(
                session,
                sso["action"],
                {
                    "pprid": sso["pprid"],
                    "NAP": sso["NAP"],
                    "ANON": sso["ANON"],
                    "t": sso["t"],
                },
            )
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            continue

        fields = _extract_hidden_fields(current)
        action = _extract_form_action(current, current_url)
        if action and "pprid" in fields and ("ipt" in fields or "NAP" in fields or "t" in fields):
            logging.info(
                "security_information: auto-submitting continue form action=%s fields=%s",
                action[:240],
                sorted(fields.keys()),
            )
            resp = await _post_form(session, action, fields)
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            continue

        if action and ("fmHF" in current or fields) and fields:
            logging.info(
                "security_information: auto-submitting form action=%s fields=%s",
                action[:240],
                sorted(fields.keys()),
            )
            resp = await _post_form(session, action, fields)
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            continue

        # Already-authenticated SSO: KMSI / type=28 finish using ServerData tokens
        url_post, sft = _extract_url_post_sft(current)
        if url_post and sft:
            logging.info(
                "security_information: KMSI finish via urlPost (help-protect / login.srf)"
            )
            resp = await session.post(
                url=url_post,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=f"PPFT={sft}&canary=&LoginOptions=3&type=28&hpgrequestid=&ctx=",
                follow_redirects=True,
            )
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            if not _find_t0(current):
                # Finish often returns to login — pull wreply / proofs next
                wreply = _wreply_from_url(url) or _wreply_from_url(current_url)
                resp2 = await _get(session, wreply or _PROOFS_URL)
                current, current_url, current_status = (
                    resp2.text,
                    str(resp2.url),
                    resp2.status_code,
                )
            continue

        refresh = _meta_refresh_url(current)
        if refresh:
            logging.info("security_information: following meta refresh → %s", refresh[:240])
            resp = await _get(session, refresh)
            current, current_url, current_status = resp.text, str(resp.url), resp.status_code
            continue

        logging.warning(
            "security_information: bridge stuck — no t0/redirect/form "
            "(missing_sso=%s) %s",
            missing,
            _page_debug(current, url=current_url, status=current_status),
        )
        break

    return current, current_url, current_status


async def security_information(session: httpx.AsyncClient):
    sec_info = await session.get(url=_PROOFS_URL, follow_redirects=True)
    logging.info(
        "security_information: initial proofs GET — %s",
        _page_debug(sec_info.text, url=str(sec_info.url), status=sec_info.status_code),
    )

    text = sec_info.text
    url = str(sec_info.url)
    status = sec_info.status_code

    match = _find_t0(text)
    if not match:
        text, url, status = await _bridge_to_proofs(session, text, url, status)
        match = _find_t0(text)

    if not match:
        logging.info("security_information: retrying proofs/Manage/additional after bridge")
        retry = await session.get(url=_PROOFS_URL, follow_redirects=True)
        logging.info(
            "security_information: retry GET — %s",
            _page_debug(retry.text, url=str(retry.url), status=retry.status_code),
        )
        text, url, status = retry.text, str(retry.url), retry.status_code
        if not _find_t0(text):
            text, url, status = await _bridge_to_proofs(session, text, url, status)
        match = _find_t0(text)

    if not match:
        _, missing = _sso_fields(text)
        raise RuntimeError(
            "security_information: could not find var t0= on proofs page after SSO bridge. "
            f"missing_sso_fields={missing} "
            f"{_page_debug(text, url=url, status=status)}"
        )

    return match.group(1)
