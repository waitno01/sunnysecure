from urllib.parse import unquote
import logging
import json
import httpx
import re


async def change_alias(session: httpx.AsyncClient, email: str, canary: str, apicanary: str) -> bool:
    """Add outlook alias and promote it to primary. Returns True only on confirmed success."""
    new_addr = f"{email}@outlook.com"

    add_resp = await session.post(
        url="https://account.live.com/AddAssocId?ru=&cru=&fl=",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://account.live.com",
            "Referer": "https://account.live.com/AddAssocId",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
        },
        data={
            "canary": canary,
            "PostOption": "LIVE",
            "SingleDomain": "outlook.com",
            "UpSell": "",
            "AddAssocIdOptions": "LIVE",
            "AssociatedIdLive": email,
        },
        follow_redirects=True,
    )
    add_text = (add_resp.text or "").lower()
    if any(
        m in add_text
        for m in (
            "already associated",
            "can't add",
            "cannot add",
            "try again later",
            "too many",
            "not available",
        )
    ):
        logging.error("AddAssocId rejected alias %s: %s", new_addr, add_resp.text[:400])
        print(f"[X] - Failed to add alias ({new_addr})")
        return False

    # Align with working fork: JSON body + application/json (not form-urlencoded + json=).
    make_resp = await session.post(
        url="https://account.live.com/API/MakePrimary",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "hpgid": "200176",
            "scid": "100141",
            "uiflvr": "1001",
            "canary": apicanary,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://account.live.com/AddAssocId",
        },
        content=json.dumps(
            {
                "aliasName": new_addr,
                "emailChecked": True,
                "removeOldPrimary": False,
                "uiflvr": 1001,
                "scid": 100141,
                "hpgid": 200176,
            }
        ),
    )

    try:
        data = make_resp.json() if make_resp.text.strip() else {}
    except json.JSONDecodeError:
        logging.error(
            "MakePrimary non-JSON for %s status=%s body=%s",
            new_addr,
            make_resp.status_code,
            (make_resp.text or "")[:400],
        )
        print(f"[X] - Failed to change primary alias ({new_addr})")
        return False

    if "error" in data:
        err = data.get("error") or {}
        code = str(err.get("code", ""))
        # Dona-fork treats opaque 500 as success; everything else (incl. cooldown) is failure.
        if code == "500":
            print(f"[+] - Changed Primary Alias ({new_addr})")
            return True
        logging.error("MakePrimary error for %s: %s", new_addr, err)
        print(f"[X] - Failed to change primary alias ({new_addr}) — {code or err}")
        return False

    print(f"[+] - Changed Primary Alias ({new_addr})")
    return True


async def change_primary_alias(session: httpx.AsyncClient, email: str, apicanary: str) -> bool:
    try:
        response = await session.get(
            url="https://account.live.com/AddAssocId",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            },
            follow_redirects=True,
        )
        logging.info("Response from AddAssocId: %s", response.text[:500])
        code_match = re.search(r'<input[^>]*name="code"[^>]*value="([^"]+)"', response.text)
        state_match = re.search(r'<input[^>]*name="state"[^>]*value="([^"]+)"', response.text)

        if code_match and state_match:
            response = await session.post(
                url="https://account.live.com/auth/redirect",
                data={
                    "code": unquote(code_match.group(1)),
                    "state": unquote(state_match.group(1)),
                },
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )

        response = await session.get(
            url="https://account.live.com/AddAssocId",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            },
            follow_redirects=True,
        )

        canary = re.search(r'name="canary"\s+value="([^"]+)"', response.text)
        if not canary:
            print(f"[X] - Failed to change primary alias ({email}@outlook.com) — no canary")
            return False

        return await change_alias(session, email, canary.group(1), apicanary)

    except Exception as e:
        logging.error("Error changing primary alias: %s", e)
        print(f"[X] - Failed to change primary alias ({email}@outlook.com)")
        return False
