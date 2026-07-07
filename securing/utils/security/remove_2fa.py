import httpx
import logging

async def remove_2fa(session: httpx.AsyncClient, apicanary: str):
    # Disables 2FA
    
    remove = await session.post(
        "https://account.live.com/API/Proofs/DisableTfa",
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "x-ms-apiVersion": "2",
            "x-ms-apiTransport": "xhr",
            "uiflvr": "1001",
            "scid": "100109",
            "hpgid": "201030",
            "X-Requested-With": "XMLHttpRequest",          
            "canary": apicanary
        },
        json = {
            "uiflvr": 1001,
            "uaid": "abd2ca2a346c43c198c9ca7e4255f3bc",
            "scid": 100109,
            "hpgid": 201030
        }
    )

    print(f"Remove Response: {remove.text} {remove.status_code}")
    if remove.status_code == 200:
        print("[+] - Disabled 2FA")
    else:
        print("[X] - Failed to disable 2FA")
