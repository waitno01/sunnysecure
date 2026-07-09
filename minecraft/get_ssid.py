import logging

import httpx

from minecraft.retry import TransientMCError, with_retries

log = logging.getLogger(__name__)


async def _get_ssid_once(xbl: str) -> str | None:
    async with httpx.AsyncClient(timeout=30.0) as session:
        response = await session.post(
            url="https://api.minecraftservices.com/authentication/login_with_xbox",
            json={
                "identityToken": xbl,
                "ensureLegacyEnabled": True,
            },
        )

        if response.status_code in (408, 425, 429, 500, 502, 503, 504):
            raise TransientMCError(
                f"login_with_xbox status {response.status_code}",
                status=response.status_code,
            )

        try:
            jresponse = response.json()
        except Exception as exc:
            raise TransientMCError(f"login_with_xbox non-JSON: {exc}") from exc

        if "access_token" in jresponse:
            return jresponse["access_token"]

        # 401/403 with error payload usually means no MC ownership — don't retry forever
        err = jresponse.get("error") or jresponse.get("errorMessage") or ""
        if response.status_code in (401, 403) and "NOT_FOUND" not in str(err).upper():
            # Some auth races return 401 briefly after XBL mint
            raise TransientMCError(f"login_with_xbox auth race: {err or response.status_code}")

        return None


async def get_ssid(xbl: str) -> str | None:
    return await with_retries(
        "get_ssid",
        lambda: _get_ssid_once(xbl),
        attempts=3,
        base_delay=2.0,
        retry_on_none=False,
    )
