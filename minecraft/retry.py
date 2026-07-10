import asyncio
import logging
from typing import Any, Awaitable, Callable, TypeVar

import httpx

try:
    import httpcore
except ImportError:  # pragma: no cover
    httpcore = None  # type: ignore

log = logging.getLogger(__name__)

T = TypeVar("T")

# Transient HTTP statuses that should be retried
RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}

_NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    httpx.HTTPError,
    httpx.TimeoutException,
    OSError,
)
if httpcore is not None:
    _NETWORK_ERRORS = _NETWORK_ERRORS + (
        httpcore.NetworkError,
        httpcore.RemoteProtocolError,
        httpcore.LocalProtocolError,
    )


class TransientMCError(Exception):
    """Raised when an MC/Xbox API call failed for a retryable reason."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def is_retryable_status(status: int | None) -> bool:
    return status is not None and status in RETRY_STATUSES


async def with_retries(
    label: str,
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    retry_on_none: bool = False,
) -> T | None:
    """Run an async callable with backoff on TransientMCError / network errors.

    If retry_on_none is True, a None return is also retried (useful when
    parsers return None on rate-limit HTML / empty bodies).
    """
    last: Any = None
    for attempt in range(1, attempts + 1):
        try:
            result = await fn()
        except TransientMCError as exc:
            last = None
            log.warning("%s attempt %s/%s transient: %s", label, attempt, attempts, exc)
            if attempt >= attempts:
                return None
            await asyncio.sleep(base_delay * attempt)
            continue
        except _NETWORK_ERRORS as exc:
            last = None
            log.warning("%s attempt %s/%s network: %s", label, attempt, attempts, exc)
            if attempt >= attempts:
                return None
            await asyncio.sleep(base_delay * attempt)
            continue
        except Exception:
            log.exception("%s attempt %s/%s crashed", label, attempt, attempts)
            if attempt >= attempts:
                return None
            await asyncio.sleep(base_delay * attempt)
            continue

        if result is None and retry_on_none and attempt < attempts:
            log.warning("%s attempt %s/%s returned None — retrying", label, attempt, attempts)
            await asyncio.sleep(base_delay * attempt)
            continue

        return result

    return last
