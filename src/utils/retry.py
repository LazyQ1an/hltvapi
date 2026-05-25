"""
Intelligent retry logic with exponential backoff and jitter.

Provides both synchronous and asynchronous retry decorators/functions
that integrate with the HLTV scraper's error hierarchy.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from src.exceptions import HTTPError, RateLimitError

F = TypeVar("F", bound=Callable[..., Any])


def _compute_delay(
    attempt: int,
    base_delay: float,
    backoff: float,
    max_delay: float = 60.0,
    jitter: bool = True,
) -> float:
    """Calculate delay with exponential backoff and optional jitter.

    Args:
        attempt: Current attempt number (0-indexed).
        base_delay: Base delay in seconds.
        backoff: Multiplier for exponential backoff.
        max_delay: Maximum delay cap.
        jitter: Whether to add random jitter.

    Returns:
        Delay in seconds.
    """
    delay = min(base_delay * (backoff ** attempt), max_delay)
    if jitter:
        delay = delay * (0.5 + random.random() * 0.5)
    return delay


def _is_retryable(error: Exception, retry_on_status: list[int]) -> bool:
    """Check if an error should trigger a retry.

    Args:
        error: The raised exception.
        retry_on_status: HTTP status codes that trigger retry.

    Returns:
        True if the error is retryable.
    """
    if isinstance(error, RateLimitError):
        return True
    if isinstance(error, HTTPError) and error.status_code in retry_on_status:
        return True
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    return False


async def async_retry(
    coro: Callable[..., Awaitable[Any]],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    retry_on_status: list[int] | None = None,
    logger: Any = None,
    **kwargs: Any,
) -> Any:
    """Execute an async function with retry logic.

    Args:
        coro: Async function to call.
        *args: Positional arguments for the function.
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay between retries.
        backoff: Exponential backoff multiplier.
        retry_on_status: HTTP status codes triggering retry.
        logger: Logger instance for logging retries.
        **kwargs: Keyword arguments for the function.

    Returns:
        The result of the coroutine.

    Raises:
        The last exception encountered if all retries are exhausted.
    """
    if retry_on_status is None:
        retry_on_status = [429, 500, 502, 503, 504]

    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await coro(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < max_retries and _is_retryable(e, retry_on_status):
                delay = _compute_delay(attempt, base_delay, backoff)
                if logger:
                    logger.warning(
                        "Retry %d/%d after error: %s. Waiting %.2fs...",
                        attempt + 1, max_retries, e, delay,
                    )
                await asyncio.sleep(delay)
            else:
                raise

    # Should not reach here, but for type safety
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Unexpected: no exception and no result from retry loop")


def sync_retry(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff: float = 2.0,
    retry_on_status: list[int] | None = None,
    logger: Any = None,
    **kwargs: Any,
) -> Any:
    """Execute a synchronous function with retry logic.

    Args:
        fn: Function to call.
        *args: Positional arguments for the function.
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay between retries.
        backoff: Exponential backoff multiplier.
        retry_on_status: HTTP status codes triggering retry.
        logger: Logger instance for logging retries.
        **kwargs: Keyword arguments for the function.

    Returns:
        The result of the function.

    Raises:
        The last exception encountered if all retries are exhausted.
    """
    if retry_on_status is None:
        retry_on_status = [429, 500, 502, 503, 504]

    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < max_retries and _is_retryable(e, retry_on_status):
                delay = _compute_delay(attempt, base_delay, backoff)
                if logger:
                    logger.warning(
                        "Retry %d/%d after error: %s. Waiting %.2fs...",
                        attempt + 1, max_retries, e, delay,
                    )
                time.sleep(delay)
            else:
                raise

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Unexpected: no exception and no result from retry loop")
