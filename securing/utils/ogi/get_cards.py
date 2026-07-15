import logging

import httpx

from securing.utils.ogi.amc_headers import amc_api_headers

log = logging.getLogger(__name__)


async def _via_msadelegate(session: httpx.AsyncClient) -> dict | None:
    from securing.utils.cookies.get_msadelegate import get_msadelegate

    token = await get_msadelegate(session)
    if not token:
        return None
    try:
        resp = await session.get(
            "https://paymentinstruments.mp.microsoft.com/v6.0/users/me/paymentInstrumentsEx"
            "?status=active,removed&language=en-US&partner=northstarweb",
            headers={
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Authorization": f"MSADELEGATE1.0={token}",
            },
            follow_redirects=True,
        )
    except Exception:
        log.exception("get_cards msadelegate request failed")
        return None

    body = resp.text or ""
    if not body.strip():
        return None
    try:
        data = resp.json()
    except Exception:
        log.warning("get_cards msadelegate: non-JSON status=%s", resp.status_code)
        return None

    # paymentInstrumentsEx returns a list of instruments
    instruments: list = []
    if isinstance(data, list):
        for card in data:
            if not isinstance(card, dict):
                continue
            # Match dona: only stored instruments with a display name + creation time
            if not card.get("creationDateTime"):
                continue
            display = (card.get("paymentMethod") or {}).get("display") or {}
            name = display.get("name") or card.get("paymentMethodType")
            if not name:
                continue
            instruments.append(
                {
                    "paymentMethodType": name,
                    "lastFourDigits": (
                        display.get("lastFourDigits")
                        or card.get("lastFourDigits")
                        or "????"
                    ),
                    "expirationDate": card.get("expirationDate") or display.get("expiry"),
                    "creationDateTime": card.get("creationDateTime"),
                }
            )
        print(f"[+] - Cards via MSADELEGATE ({len(instruments)})")
        return {"paymentInstruments": instruments}

    if isinstance(data, dict) and data.get("paymentInstruments") is not None:
        return data
    return None


async def get_cards(session: httpx.AsyncClient, verification_token: str):
    via_pi = await _via_msadelegate(session)
    if via_pi is not None:
        return via_pi

    try:
        cards = await session.get(
            "https://account.microsoft.com/home/api/payment-instruments/pi-summary",
            headers=amc_api_headers(
                session,
                verification_token,
                qos_root="GLOBAL.HOME.PAYMENTINSTRUMENTS.GETPAYMENTINSTRUMENTSSUMMARY",
            ),
            follow_redirects=True,
        )
    except Exception:
        log.exception("get_cards request failed")
        return {"paymentInstruments": []}

    body = cards.text or ""
    if not body.strip():
        return {"paymentInstruments": []}
    try:
        data = cards.json()
    except Exception:
        log.warning("get_cards: non-JSON status=%s", cards.status_code)
        return {"paymentInstruments": []}
    if not isinstance(data, dict):
        return {"paymentInstruments": []}
    if data.get("error") and not data.get("paymentInstruments"):
        log.warning("get_cards: API error %s", data.get("error"))
        return {"paymentInstruments": []}
    data.setdefault("paymentInstruments", [])
    return data
