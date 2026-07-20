import logging
import httpx

async def remove_zyger(session: httpx.AsyncClient, apicanary: str):
    # Removes login through pass keys aka Zyger / Windows Hello
    
    remove = await session.post(
        url = "https://account.live.com/API/Proofs/RevokeWindowsHelloProofs",
        headers = {
            "host": "account.live.com",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "canary": apicanary
        },
        json = {
            "uiflvr": 1001,
            "uaid": "abd2ca2a346c43c198c9ca7e4255f3bc",
            "scid": 100109,
            "hpgid": 201030
        },
        follow_redirects = False
    )

    body = remove.text or ""
    err_code = None
    try:
        data = remove.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            err_code = err.get("code")
        elif err is not None:
            err_code = err
    except Exception:
        data = None

    # MS often returns HTTP 200 with {"error":{"code":"6001"}} — treat as failure.
    if remove.status_code == 200 and not err_code:
        print("[+] - Removed Zyger")
        return True

    print(f"[X] - Failed to remove Zyger (status={remove.status_code} err={err_code})")
    logging.error("Failed to remove Zyger: %s", body[:500])
    return False
