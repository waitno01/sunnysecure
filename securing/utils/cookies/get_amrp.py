import logging

import httpx


async def get_amrp(session: httpx.AsyncClient, T: str | None) -> bool:
    """Post the login ``t`` token to proofs/Add to establish AMRP session state.

    Returns True if the post was attempted, False if skipped (no token).
    Failures are non-fatal — modern sessions often already have MSPAuth/WLSSC.
    """
    if not T:
        logging.info("get_amrp: skipped (no t token)")
        return False

    try:
        await session.post(
            url="https://account.live.com/proofs/Add?apt=2&wa=wsignin1.0",
            data={"t": T},
            follow_redirects=False,
        )
        return True
    except Exception:
        logging.exception("get_amrp post failed")
        return False
