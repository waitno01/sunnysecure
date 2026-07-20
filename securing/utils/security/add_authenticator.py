from shared.gen_totp import totp
import httpx
import json
import logging
import re

log = logging.getLogger("bot")


async def add_authenticator(session: httpx.AsyncClient) -> str:
    """Add Microsoft Authenticator TOTP proof and enable TFA. Returns secret key."""
    proof_add = await session.get(
        url="https://account.live.com/proofs/Add?mpsplit=2&apt=3&mkt=en-US"
    )
    body = proof_add.text or ""

    secret_m = re.search(r"[a-z0-9]{4}(?:&nbsp;[a-z0-9]{4}){3}", body, re.I)
    if not secret_m:
        # Alternate layouts: spaced secret without nbsp, or data-secret attrs
        secret_m = re.search(
            r"(?:secret|SecretKey|otpauth)[^A-Z0-9]*([A-Z2-7]{16,64})",
            body,
            re.I,
        )
    if not secret_m:
        raise RuntimeError(
            f"add_authenticator: could not find TOTP secret (status={proof_add.status_code})"
        )
    secret_key = secret_m.group(0).replace("&nbsp;", "").replace(" ", "").strip()
    # If we captured a long otpauth match group, prefer group 1
    if secret_m.lastindex:
        secret_key = secret_m.group(1).replace(" ", "").strip()

    proof_m = re.search(r'id="ProofId"[^>]*value="(\d+)"', body)
    if not proof_m:
        proof_m = re.search(r'"ProofId"\s*:\s*"?(\d+)"?', body)
    if not proof_m:
        raise RuntimeError("add_authenticator: ProofId missing on Add page")
    proof_id = proof_m.group(1)

    canary_m = re.search(r'"apiCanary"\s*:\s*"([^"]+)"', body)
    tcxt_m = re.search(r'"tcxt"\s*:\s*"([^"]+)"', body)
    if not canary_m or not tcxt_m:
        raise RuntimeError("add_authenticator: apiCanary/tcxt missing on Add page")
    canary = json.loads(f'"{canary_m.group(1)}"')
    tcxt = json.loads(f'"{tcxt_m.group(1)}"')

    otp = await totp(secret_key)
    verify = await session.post(
        url="https://account.live.com/API/AddVerifyTotp",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Canary": canary,
            "Tcxt": tcxt,
        },
        json={
            "ProofId": proof_id,
            "TotpCode": otp,
            "uiflvr": 1001,
            "scid": 100109,
            "hpgid": 200335,
        },
        follow_redirects=True,
    )
    if verify.status_code >= 400:
        log.warning(
            "AddVerifyTotp status=%s body=%s",
            verify.status_code,
            (verify.text or "")[:200],
        )

    default_url = await session.get(url="https://account.live.com/proofs/EnableTfa")
    enable_body = default_url.text or ""
    enable_m = re.search(r'"EnableTfa"\s*:\s*"([^"]+)"', enable_body)
    if enable_m:
        enable_2fa = enable_m.group(1)
        # Unescape JSON unicode if present
        try:
            enable_2fa = json.loads(f'"{enable_2fa}"')
        except Exception:
            pass
        await session.get(url=enable_2fa)
    else:
        # Some accounts already have TFA toggled after AddVerifyTotp
        log.warning("EnableTfa link missing — secret may still be valid")
        print("[!] - EnableTfa link missing after AddVerifyTotp (continuing with secret)")

    return secret_key.lower()
