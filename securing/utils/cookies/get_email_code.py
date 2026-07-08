from database.database import DBConnection
import asyncio
import re
import time


async def get_email_code(mail: str, timeout: float = 120) -> str | None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        with DBConnection() as db:
            row = db.mark_unused(mail)

        if row:
            email_id, body = row
            match = re.search(r'\b(\d{6})\b', body)
            if match:
                with DBConnection() as db:
                    db.mark_used(email_id)
                return match.group(1)

        await asyncio.sleep(0.8)

    return None
