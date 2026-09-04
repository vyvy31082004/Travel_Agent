"""Serialize RapidAPI HTTP calls across parallel domain branches and MCP processes."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

T = TypeVar("T")

_THREAD_LOCK = threading.Lock()
_RATE_LIMIT_MESSAGE = "RapidAPI bị giới hạn request. Hãy thử lại sau."
_LOCK_PATH = Path(
    os.getenv(
        "RAPIDAPI_LOCK_FILE",
        str(Path(tempfile.gettempdir()) / "customer_support_agent_rapidapi.lock"),
    )
)


@contextmanager
def _cross_process_lock() -> Iterator[None]:
    """
    Best-effort lock shared across MCP worker processes on the same machine.
  Falls back to in-thread lock if OS locking is unavailable.
    """
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK_PATH.open("a+", encoding="utf-8") as handle:
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.15)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def rapidapi_retry_delays(retries: int) -> list[float]:
    """Backoff delays in seconds after a 429 (2s, 5s, ...)."""
    base = [2.0, 5.0, 8.0]
    return base[: max(retries, 0)]


def is_rate_limit_error(exc: BaseException) -> bool:
    return _RATE_LIMIT_MESSAGE in str(exc)


def with_rapidapi_limit(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a sync RapidAPI call under a cross-process lock."""
    with _THREAD_LOCK, _cross_process_lock():
        return fn(*args, **kwargs)


def call_with_rate_limit_retry(
    fn: Callable[[], T],
    *,
    retries: int = 2,
    on_retry: Callable[[int, float, BaseException], None] | None = None,
) -> T:
    """Execute fn under the RapidAPI lock, retrying 429 errors with backoff."""
    delays = rapidapi_retry_delays(retries)
    last_exc: BaseException | None = None

    for attempt in range(retries + 2):
        try:
            return with_rapidapi_limit(fn)
        except RuntimeError as exc:
            if not is_rate_limit_error(exc):
                raise
            last_exc = exc
            if attempt > retries:
                break
            delay = delays[attempt] if attempt < len(delays) else delays[-1]
            if on_retry:
                on_retry(attempt + 1, delay, exc)
            time.sleep(delay)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("RapidAPI call failed.")
